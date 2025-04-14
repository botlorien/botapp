import re
from .models import Bot, Task
from .decorators import task
from django.db import connection
from django.conf import settings
from django.core.management import call_command


class BotApp:
    def __init__(self, db_name):
        self.db_name = db_name
        connection.settings_dict["NAME"] = db_name
        self.bot_instance = None

    def set_bot(self, bot_name, bot_description, bot_version, bot_department):
        bot_name = str(bot_name).strip().capitalize()
        bot_description = str(bot_description).strip().capitalize()
        bot_version = str(bot_version).strip()
        bot_department = str(bot_department).strip().upper()

        bot, created = Bot.objects.get_or_create(
            name=bot_name,
            defaults={
                'description': bot_description,
                'version': bot_version,
                'department': bot_department,
            }
        )

        # Atualiza os dados se o bot já existia
        if not created:
            updated = False
            if bot.description != bot_description:
                bot.description = bot_description
                updated = True
            if bot.version != bot_version:
                bot.version = bot_version
                updated = True
            if bot.department != bot_department:
                bot.department = bot_department
                updated = True
            if updated:
                bot.save()

        self.bot_instance = bot

    def _get_or_create_task(self, func):
        if self.bot_instance is None:
            raise Exception("Bot not set. Call app.set_bot first.")
        
        # Substitui qualquer caractere que não seja alfanumérico por espaço
        cleaned_name = re.sub(r'[^a-zA-Z0-9]', ' ', func.__name__)

        task, created = Task.objects.get_or_create(
            bot=self.bot_instance,
            name=cleaned_name,
            defaults={'description': func.__doc__ or ''}
        )

        # Atualiza a descrição se ela mudou (ex: docstring foi alterada no código)
        new_description = func.__doc__ or ''
        if not created and task.description != new_description:
            task.description = new_description
            task.save()

        return task

    def task(self, func):
        return task(self, func)

    def open_admin(self):
        try:
            call_command('runserver', f'0.0.0.0:{settings.PORT_ADMIN}')
        except Exception as e:
            print(f"⚠️ Erro ao rodar o servidor: {e}")
