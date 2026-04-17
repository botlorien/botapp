"""Loop blocante que roda `check_alerts` a cada N segundos.

Feito para rodar como processo separado ao lado do gunicorn — em prod, um
container dedicado; em dev, em outro terminal. Esse desacoplamento evita
que workers do gunicorn dupliquem detecções ou corram entre si.

Uso:
  python manage.py run_alert_scheduler                  # intervalo do env (default 60s)
  python manage.py run_alert_scheduler --interval 30
  python manage.py run_alert_scheduler --once           # roda uma vez e sai

Env vars:
  BOTAPP_ALERT_SCHEDULER_INTERVAL_SECONDS (default 60)
"""
import logging
import os
import signal
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Loop que executa check_alerts em intervalo configurável.'

    def add_arguments(self, parser):
        default = int(os.environ.get('BOTAPP_ALERT_SCHEDULER_INTERVAL_SECONDS', '60'))
        parser.add_argument('--interval', type=int, default=default,
                            help=f'Segundos entre execuções (default {default}).')
        parser.add_argument('--once', action='store_true',
                            help='Roda uma vez e sai — útil para cron externo.')

    def handle(self, *args, **opts):
        interval = max(5, int(opts['interval']))
        once = opts['once']

        self._stop = False

        def _graceful(signum, _frame):
            logger.info('alert_scheduler: signal %s, encerrando.', signum)
            self._stop = True

        # SIGTERM/SIGINT para shutdown limpo (Docker/k8s, Ctrl+C)
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _graceful)
            except (ValueError, OSError):
                # signal pode não estar disponível em thread não-principal
                pass

        self.stdout.write(self.style.SUCCESS(
            f'alert_scheduler iniciado (interval={interval}s, once={once})'
        ))

        while not self._stop:
            start = time.monotonic()
            try:
                call_command('check_alerts')
            except Exception:
                logger.exception('alert_scheduler: check_alerts falhou — continuando.')

            if once:
                break

            elapsed = time.monotonic() - start
            sleep_for = max(1, interval - elapsed)
            # Dorme em pedaços de 1s para responder rápido ao signal
            slept = 0
            while slept < sleep_for and not self._stop:
                time.sleep(min(1, sleep_for - slept))
                slept += 1

        self.stdout.write(self.style.WARNING('alert_scheduler encerrado.'))
