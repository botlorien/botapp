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

class ForwardedPrefixMiddleware:
    """Suporte a montagem sob um prefixo via ``X-Forwarded-Prefix`` (quando o
    dashboard é servido atrás de um reverse-proxy same-origin, ex.: embutido em
    outro portal). Seta SCRIPT_NAME no environ WSGI ANTES do Django, para
    ``reverse()``/``{% static %}``/redirects já gerarem URLs com o prefixo. Sem o
    header (acesso direto), nada muda. Genérico — não depende de nenhum host."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        prefix = environ.get("HTTP_X_FORWARDED_PREFIX", "").rstrip("/")
        if prefix:
            environ["SCRIPT_NAME"] = prefix
        return self.app(environ, start_response)


application = ForwardedPrefixMiddleware(get_wsgi_application())  # Django WSGI application
