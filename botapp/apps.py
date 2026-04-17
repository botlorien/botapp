import logging
import os
import sys
import threading
import time

from django.apps import AppConfig

logger = logging.getLogger(__name__)

# Guard contra double-start quando o autoreloader do runserver executa
# ready() múltiplas vezes no mesmo processo.
_scheduler_started = False


def _alert_scheduler_loop(interval):
    """Thread daemon: loopa check_alerts. Só para dev/single-worker.

    Em produção com gunicorn multi-worker use `manage.py run_alert_scheduler`
    como processo separado. N workers * N schedulers = desperdício e possível
    race ao criar alertas.
    """
    from django.core.management import call_command

    # Pequeno delay para não competir com a inicialização do servidor.
    time.sleep(5)
    logger.info('alert_scheduler in-process iniciado (interval=%ds)', interval)

    while True:
        try:
            call_command('check_alerts')
        except Exception:
            logger.exception('alert_scheduler in-process: check_alerts falhou.')
        time.sleep(max(5, interval))


class BotAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'botapp'
    verbose_name = 'Gerenciador de Bots RPA'

    def ready(self):
        # Importa signals quando o app estiver pronto.
        from . import signals  # noqa: F401
        self._maybe_start_in_process_scheduler()

    def _maybe_start_in_process_scheduler(self):
        global _scheduler_started

        if _scheduler_started:
            return
        if os.environ.get('BOTAPP_ALERT_SCHEDULER_ENABLED', '').lower() not in ('1', 'true', 'yes'):
            return

        # Runserver: o autoreloader roda em um processo-pai separado que não
        # deve iniciar a thread — só o filho (RUN_MAIN=true).
        if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
            return

        # Não iniciar dentro de comandos de gerência (migrate, makemigrations, etc).
        cmd_safe = {'runserver', 'gunicorn'}
        if sys.argv and len(sys.argv) > 1 and sys.argv[1] not in cmd_safe:
            return

        interval = int(os.environ.get('BOTAPP_ALERT_SCHEDULER_INTERVAL_SECONDS', '60'))
        t = threading.Thread(
            target=_alert_scheduler_loop,
            args=(interval,),
            name='botapp-alert-scheduler',
            daemon=True,
        )
        t.start()
        _scheduler_started = True
