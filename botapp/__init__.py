import os

# Só inicializa se for standalone
if os.environ.get('BOTAPP_AUTOINIT', '1') == '1':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'botapp.settings')
    import django
    django.setup()

from django.conf import settings
from .core import BotApp
