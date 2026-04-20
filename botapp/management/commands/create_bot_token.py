"""Cria ou recupera um Token DRF para um usuário existente.

Uso:
    python manage.py create_bot_token <username>
    python manage.py create_bot_token <username> --rotate

O token resultante deve ser exportado como `BOTAPP_API_TOKEN` no ambiente
dos RPAs para substituir `BOTAPP_API_USUARIO`/`BOTAPP_API_SENHA` (Basic
Auth depreciado). O SDK (Python e Go) detecta `BOTAPP_API_TOKEN` e usa
automaticamente o header `Authorization: Token <...>`.

Migração recomendada:
    1. Rodar este comando no container do dashboard
    2. Injetar o token nas variáveis CI/CD (GitLab) como BOTAPP_API_TOKEN
    3. Remover BOTAPP_API_USUARIO/BOTAPP_API_SENHA das envs dos RPAs
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.authtoken.models import Token


class Command(BaseCommand):
    help = 'Cria/recupera Token DRF para um usuário (para autenticação do SDK botapp).'

    def add_arguments(self, parser):
        parser.add_argument('username', help='Username do usuário dono do token')
        parser.add_argument(
            '--rotate',
            action='store_true',
            help='Revoga token existente e gera novo (use ao comprometimento).',
        )

    def handle(self, *args, **opts):
        User = get_user_model()
        username = opts['username']

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"Usuário '{username}' não existe.")

        if opts['rotate']:
            Token.objects.filter(user=user).delete()
            token = Token.objects.create(user=user)
            self.stdout.write(self.style.WARNING(
                f'Token rotacionado para {username}. Token anterior foi revogado.'
            ))
        else:
            token, created = Token.objects.get_or_create(user=user)
            if created:
                self.stdout.write(self.style.SUCCESS(
                    f'Token criado para {username}.'
                ))
            else:
                self.stdout.write(self.style.NOTICE(
                    f'Token já existia para {username} — retornando o existente.'
                ))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'BOTAPP_API_TOKEN={token.key}'))
        self.stdout.write('')
        self.stdout.write(
            'Defina essa variável no ambiente dos RPAs (CI/CD) e remova '
            'BOTAPP_API_USUARIO/BOTAPP_API_SENHA quando todos tiverem migrado.'
        )
