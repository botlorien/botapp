# botapp/__init__.py

import os
import logging

# Boa prática de pacote: adiciona NullHandler no namespace 'botapp'
# para que o SDK não emita logs se o projeto hospedeiro não tiver
# configurado um handler. O host é soberano sobre o logging.
logging.getLogger(__name__).addHandler(logging.NullHandler())

_logger = logging.getLogger(__name__)

# Detecta se está standalone
STANDALONE_MODE = 'DJANGO_SETTINGS_MODULE' not in os.environ

if STANDALONE_MODE:
    _logger.info("botapp em modo standalone — inicializando settings do pacote")
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
    _logger.info("botapp em modo plugin — usando cliente REST (BotAppRestful)")
    # from .rest_server import start_rest_server
    # start_rest_server()
    from .core_restful import BotAppRestful as BotApp


__all__ = ['BotApp']
