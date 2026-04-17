"""Repara drift de Bot.last_execution_at / last_status.

Problema: o post_save de TaskLog só dispara no processo que salvou o log.
Bots em modo standalone com versão antiga do SDK (sem signals.py) escrevem
direto no DB e deixam Bot.last_* atrasado — o dashboard mostra "Última
execução" defasada e o detector `silent_bot` gera alertas falsos.

Uso:
  python manage.py reconcile_bot_denorm              # todos os bots
  python manage.py reconcile_bot_denorm --bot-id 42  # um bot específico
"""
from django.core.management.base import BaseCommand

from botapp.signals import reconcile_bot_last_execution


class Command(BaseCommand):
    help = 'Repara Bot.last_execution_at/last_status a partir do TaskLog real.'

    def add_arguments(self, parser):
        parser.add_argument('--bot-id', type=int, action='append', default=None,
                            help='Restringe a um bot (pode repetir). Default: todos.')

    def handle(self, *args, **opts):
        bot_ids = opts.get('bot_id')
        count = reconcile_bot_last_execution(bot_ids=bot_ids)
        self.stdout.write(self.style.SUCCESS(
            f'{count} bot(s) atualizado(s).'
        ))
