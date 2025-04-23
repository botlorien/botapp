# botapp/__init__.py

import os

# teste
#os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'botapp.settings')

# Detecta se está standalone
STANDALONE_MODE = 'DJANGO_SETTINGS_MODULE' not in os.environ

if STANDALONE_MODE:
    print("Modo standalone: inicializando settings para BOTAPP.")
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'botapp.settings')
    import django
    django.setup()

    from .core import BotApp

from django.conf import settings

# Se for plugin (usado dentro de outro projeto Django)
def is_inside_django_project():
    # settings.configured já deve estar True aqui
    return not STANDALONE_MODE and settings.ROOT_URLCONF != 'botapp.urls'

# Executa servidor REST isolado apenas em modo plugin
if is_inside_django_project():
    print("Modo plugin detectado: rodando servidor REST isolado.")
    # from .rest_server import start_rest_server
    # start_rest_server()
    from .core_restful import BotAppRestful as BotApp


__all__ = ['BotApp']
