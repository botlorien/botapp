"""Loop blocante que sincroniza o CI em intervalo configurável.

Mesmo desenho do `run_alert_scheduler`: processo separado ao lado do gunicorn,
para que workers web não dupliquem sincronização nem corram entre si.

Uso:
  python manage.py run_ci_scheduler                 # intervalo do env
  python manage.py run_ci_scheduler --interval 300
  python manage.py run_ci_scheduler --once          # uma vez e sai (cron externo)

Env vars:
  BOTAPP_CI_POLL_INTERVAL_MINUTES (default 15)
"""
import logging
import os
import signal
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Loop que executa sync_ci em intervalo configurável.'

    def add_arguments(self, parser):
        try:
            minutos = int(os.environ.get('BOTAPP_CI_POLL_INTERVAL_MINUTES', '15'))
        except ValueError:
            minutos = 15
        parser.add_argument('--interval', type=int, default=minutos * 60,
                            help=f'Segundos entre ciclos (default {minutos * 60}).')
        parser.add_argument('--once', action='store_true',
                            help='Roda uma vez e sai.')

    def handle(self, *args, **opts):
        intervalo = max(60, int(opts['interval']))
        self._parar = False

        def _sinal(signum, _frame):
            # encerra ao FIM do ciclo: matar no meio deixaria cursor de projeto
            # avançado sem os jobs correspondentes gravados
            self._parar = True
            self.stdout.write(f'\nsinal {signum} recebido; encerrando após o ciclo.')

        signal.signal(signal.SIGTERM, _sinal)
        signal.signal(signal.SIGINT, _sinal)

        while not self._parar:
            inicio = time.time()
            try:
                call_command('sync_ci')
            except Exception:
                # um ciclo com exceção não pode derrubar o scheduler
                logger.exception('ciclo de sync_ci falhou; segue para o próximo')
            if opts['once'] or self._parar:
                break
            gasto = time.time() - inicio
            time.sleep(max(5, intervalo - gasto))
