"""Sincroniza as conexões de CI: descobre projetos/agendamentos e busca execuções.

Uso:
  python manage.py sync_ci                    # todas as conexões habilitadas
  python manage.py sync_ci --connection nome  # só uma
  python manage.py sync_ci --discovery        # força a descoberta agora
  python manage.py sync_ci --bootstrap        # cria a conexão a partir do env

Env vars: ver docs/ci-integration-design.md §9.
"""
import json

from django.core.management.base import BaseCommand

from botapp.ci_sync import ci_enabled, sync_connection
from botapp.models import CIConnection


class Command(BaseCommand):
    help = 'Sincroniza projetos, agendamentos e pipelines do servidor de CI.'

    def add_arguments(self, parser):
        parser.add_argument('--connection', help='Nome da conexão (default: todas).')
        parser.add_argument('--discovery', action='store_true',
                            help='Força a descoberta de projetos neste ciclo.')
        parser.add_argument('--bootstrap', action='store_true',
                            help='Cria/atualiza a conexão a partir das env vars '
                                 'BOTAPP_CI_* antes de sincronizar.')

    def handle(self, *args, **opts):
        if not ci_enabled():
            self.stdout.write(self.style.WARNING(
                'BOTAPP_CI_ENABLED != true — integração de CI desligada, nada a fazer.'))
            return

        if opts['bootstrap']:
            conexao, criada = bootstrap_from_env()
            self.stdout.write(self.style.SUCCESS(
                f'conexão "{conexao.name}" {"criada" if criada else "atualizada"} '
                f'a partir do ambiente'))

        qs = CIConnection.objects.filter(enabled=True)
        if opts['connection']:
            qs = qs.filter(name=opts['connection'])
        if not qs.exists():
            self.stdout.write(self.style.WARNING(
                'nenhuma conexão habilitada — use --bootstrap ou cadastre em /ci/'))
            return

        for conexao in qs:
            resultado = sync_connection(conexao, forcar_descoberta=opts['discovery'])
            estilo = self.style.ERROR if resultado.get('erro') else self.style.SUCCESS
            self.stdout.write(estilo(json.dumps(resultado, default=str)))


def bootstrap_from_env():
    """Cria a conexão a partir do ambiente — sem nenhum valor default de servidor.

    Existe para que uma instalação em container não precise de passo manual na
    UI: as mesmas variáveis que já configuram o resto do painel bastam.
    """
    import os
    base_url = os.getenv('BOTAPP_CI_BASE_URL', '').strip()
    namespace = os.getenv('BOTAPP_CI_NAMESPACE', '').strip()
    if not base_url or not namespace:
        raise SystemExit('BOTAPP_CI_BASE_URL e BOTAPP_CI_NAMESPACE são obrigatórias '
                         'para o --bootstrap (não há default de servidor)')
    nome = os.getenv('BOTAPP_CI_CONNECTION_NAME', 'default').strip() or 'default'
    defaults = {
        'kind': 'gitlab',
        'base_url': base_url,
        'namespace': namespace,
        'token_source': 'env',
        'token_env_var': os.getenv('BOTAPP_CI_TOKEN_VAR', 'BOTAPP_CI_TOKEN'),
        'enabled': True,
    }
    for chave, env in (('discovery_interval_minutes',
                        'BOTAPP_CI_DISCOVERY_INTERVAL_MINUTES'),
                       ('poll_interval_minutes', 'BOTAPP_CI_POLL_INTERVAL_MINUTES')):
        valor = os.getenv(env, '').strip()
        if valor.isdigit():
            defaults[chave] = int(valor)
    return CIConnection.objects.update_or_create(name=nome, defaults=defaults)
