# botapp/restful.py

import re
import os
import requests
from requests.auth import HTTPBasicAuth

from .decorators import task_restful

BOTAPP_API_USUARIO = os.environ.get('BOTAPP_API_USUARIO')
BOTAPP_API_SENHA = os.environ.get('BOTAPP_API_SENHA')

class BotAppRestful:
    def __init__(self, *args, **kwargs):
        if 'BOTAPP_API_URL' not in os.environ:
            raise ValueError("Environment variable 'BOTAPP_API_URL' not set.")
        else:
            api_url = os.environ['BOTAPP_API_URL']
        self.api_url = api_url.rstrip('/')
        self.bot_instance = None
        self.bot_name = None

    def search_bot(self, bot_name):
                # Check if bot exists
        r = requests.get(f"{self.api_url}/bots/", params={'search': bot_name}, auth=HTTPBasicAuth(BOTAPP_API_USUARIO, BOTAPP_API_SENHA))
        bots = r.json()
        match = next((b for b in bots if b['name'] == bot_name), None)
        return match

    def set_bot(self, bot_name, bot_description, bot_version, bot_department):
        cleaned_name = re.sub(r'[^a-zA-Z0-9]', ' ', bot_name).strip().capitalize()
        self.bot_name = cleaned_name
        bot_description = bot_description.strip().capitalize()
        bot_version = bot_version.strip()
        bot_department = bot_department.strip().upper()

        payload = {
            'name': cleaned_name,
            'description': bot_description,
            'version': bot_version,
            'department': bot_department,
            'is_active': True
        }

        match = self.search_bot(cleaned_name)
        print(f"Bot found: {match}")
        if match:
            self.bot_instance = match
            # update if different
            updated_fields = {}
            for field in ['description', 'version', 'department']:
                if self.bot_instance[field] != payload[field]:
                    updated_fields[field] = payload[field]

            if updated_fields:
                requests.patch(f"{self.api_url}/bots/{self.bot_instance['id']}/", data=updated_fields, auth=HTTPBasicAuth(BOTAPP_API_USUARIO, BOTAPP_API_SENHA))
        else:
            r = requests.post(f"{self.api_url}/bots/", data=payload, auth=HTTPBasicAuth(BOTAPP_API_USUARIO, BOTAPP_API_SENHA))
            self.bot_instance = r.json()

    def _get_or_create_task(self, func):
        if self.bot_instance is None:
            raise Exception("Bot not set. Call set_bot() first.")

        # Check if task exists
        r = requests.get(f"{self.api_url}/tasks/", params={'bot': self.bot_instance['id'], 'name': func.__name__}, auth=HTTPBasicAuth(BOTAPP_API_USUARIO, BOTAPP_API_SENHA))
        tasks = r.json()
        match = next((t for t in tasks if t['name'] == func.__name__), None)

        if match:
            # update description if needed
            if match['description'] != (func.__doc__ or ''):
                requests.patch(f"{self.api_url}/tasks/{match['id']}/", data={'description': func.__doc__ or ''}, auth=HTTPBasicAuth(BOTAPP_API_USUARIO, BOTAPP_API_SENHA))
            return match
        else:
            payload = {
                'bot': self.bot_instance['id'],
                'name': func.__name__,
                'description': func.__doc__ or '',
            }
            r = requests.post(f"{self.api_url}/tasks/", data=payload, auth=HTTPBasicAuth(BOTAPP_API_USUARIO, BOTAPP_API_SENHA))
            return r.json()

    def task(self, func):
        return task_restful(self, func)
