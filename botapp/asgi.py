import os
from dotenv import load_dotenv
from botapp import BotApp
from django.core.asgi import get_asgi_application
from django.core.management import call_command

load_dotenv()
# Configuração do Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'botapp.settings')

try:
    call_command('collectstatic', '--noinput')
except Exception as e:
    print(f"⚠️ Erro ao coletar staticos: {e}")

# Ponto de entrada ASGI
application = get_asgi_application()
