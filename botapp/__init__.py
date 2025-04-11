import os
import django

# 1. Configura o Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'botapp.settings')
django.setup()

# 2. Cria o schema se não existir
from django.conf import settings
from botapp.db_init import ensure_schema_exists
ensure_schema_exists(settings.DATABASE_SCHEMA)

# 3. Roda makemigrations e migrate automaticamente
from django.core.management import call_command
try:
    call_command('makemigrations', interactive=False)
    call_command('migrate', interactive=False)
except Exception as e:
    print(f"⚠️ Erro durante migrações automáticas: {e}")

# 4. Criação automática de superusuário padrão
from django.contrib.auth import get_user_model

User = get_user_model()
DEFAULT_SUPERUSER = {
    'username': os.getenv('BOTAPP_SUPERUSER_USERNAME', 'admin'),
    'email': os.getenv('BOTAPP_SUPERUSER_EMAIL', 'admin@example.com'),
    'password': os.getenv('BOTAPP_SUPERUSER_PASSWORD', 'admin123'),
}

try:
    if not User.objects.filter(username=DEFAULT_SUPERUSER['username']).exists():
        print(f"🛠️ Criando superusuário padrão: {DEFAULT_SUPERUSER['username']}")
        User.objects.create_superuser(
            username=DEFAULT_SUPERUSER['username'],
            email=DEFAULT_SUPERUSER['email'],
            password=DEFAULT_SUPERUSER['password']
        )
    else:
        print(f"✅ Superusuário '{DEFAULT_SUPERUSER['username']}' já existe.")
except Exception as e:
    print(f"❌ Falha ao criar superusuário: {e}")
# 4. Expõe o BotApp
from .core import BotApp
