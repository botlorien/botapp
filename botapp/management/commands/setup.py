# botapp/management/commands/setup.py

import os
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.contrib.auth import get_user_model

from botapp.db_init import ensure_schema_exists


class Command(BaseCommand):
    help = 'Inicializa o BotApp: configura schema, migrações e superusuário'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("🔧 Iniciando configuração do BotApp..."))

        # 1. Certifica-se que o settings é o certo
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'botapp.settings')

        # 2. Garante que Django está configurado
        import django
        django.setup()

        from django.conf import settings

        # 3. Cria o schema se não existir
        self.stdout.write("🗂️ Verificando schema do banco...")
        try:
            ensure_schema_exists(settings.DATABASE_SCHEMA)
            self.stdout.write(self.style.SUCCESS(f"✔️ Schema '{settings.DATABASE_SCHEMA}' verificado no banco {settings.DATABASES['default']['NAME']}."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Erro ao garantir schema: {e}"))

        # 4. Migrations
        self.stdout.write("📦 Aplicando migrações...")
        try:
            call_command('makemigrations', interactive=False, verbosity=0)
            call_command('migrate', interactive=False, verbosity=0)
            self.stdout.write(self.style.SUCCESS("✔️ Migrações aplicadas."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"⚠️ Erro durante migrações: {e}"))

        # 5. Criação automática de superusuário
        self.stdout.write("👤 Verificando superusuário...")
        User = get_user_model()
        DEFAULT_SUPERUSER = {
            'username': os.getenv('BOTAPP_SUPERUSER_USERNAME', 'admin'),
            'email': os.getenv('BOTAPP_SUPERUSER_EMAIL', 'admin@example.com'),
            'password': os.getenv('BOTAPP_SUPERUSER_PASSWORD', 'admin123'),
        }

        # Em produção (DEBUG=False), não permite o password default 'admin123'
        if not settings.DEBUG and DEFAULT_SUPERUSER['password'] == 'admin123':
            self.stdout.write(self.style.ERROR(
                "❌ BOTAPP_SUPERUSER_PASSWORD não pode usar o default 'admin123' em produção. "
                "Defina a variável de ambiente antes de rodar `botapp setup`."
            ))
            return

        try:
            if not User.objects.filter(username=DEFAULT_SUPERUSER['username']).exists():
                User.objects.create_superuser(
                    username=DEFAULT_SUPERUSER['username'],
                    email=DEFAULT_SUPERUSER['email'],
                    password=DEFAULT_SUPERUSER['password']
                )
                self.stdout.write(self.style.SUCCESS(f"🛠️ Superusuário '{DEFAULT_SUPERUSER['username']}' criado com sucesso."))
            else:
                self.stdout.write(self.style.WARNING(f"✅ Superusuário '{DEFAULT_SUPERUSER['username']}' já existe."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Falha ao criar superusuário: {e}"))

        # 6. Instancia o BotApp (opcional)
        try:
            from botapp.core import BotApp
            app = BotApp(os.environ.get('PG_BOTAPP_DBNAME'))
            self.stdout.write(self.style.SUCCESS("🚀 BotApp iniciado com sucesso."))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"⚠️ BotApp não pôde ser iniciado: {e}"))
