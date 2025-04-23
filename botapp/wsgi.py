# botapp/wsgi.py

import os
from dotenv import load_dotenv
from botapp import BotApp
from django.core.wsgi import get_wsgi_application
from django.core.management import call_command

load_dotenv()
# Defina o aplicativo como o ponto de entrada WSGI
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'botapp.settings')
try:
    call_command('collectstatic', '--noinput')
except Exception as e:
    print(f"⚠️ Erro ao coletar staticos: {e}")

application = get_wsgi_application() # Django WSGI application
