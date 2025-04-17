import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'botapp.settings')
django.setup()

from django.conf import settings  # <- agora é seguro

# 4. Expõe o BotApp
from .core import BotApp
