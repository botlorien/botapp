# botapp/restful.py

import re
import os
import logging
import requests

from .decorators import task_restful, _auth_kwargs

logger = logging.getLogger(__name__)

BOTAPP_API_TIMEOUT = float(os.environ.get('BOTAPP_API_TIMEOUT', '10'))


class BotAppRestful:
    def __init__(self, *args, **kwargs):
        if 'BOTAPP_API_URL' not in os.environ:
            raise ValueError("Environment variable 'BOTAPP_API_URL' not set.")
        else:
            api_url = os.environ['BOTAPP_API_URL']
        self.api_url = api_url.rstrip('/')
        self.bot_instance = None
        self.bot_name = None
        logger.debug("BotAppRestful inicializado api_url=%s", self.api_url)

    def search_bot(self, bot_name):
        r = requests.get(
            f"{self.api_url}/bots/",
            params={'search': bot_name},
            timeout=BOTAPP_API_TIMEOUT,
            **_auth_kwargs(),
        )
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
        if match:
            self.bot_instance = match
            updated_fields = {}
            for field in ['description', 'version', 'department']:
                if self.bot_instance[field] != payload[field]:
                    updated_fields[field] = payload[field]

            if updated_fields:
                requests.patch(
                    f"{self.api_url}/bots/{self.bot_instance['id']}/",
                    data=updated_fields,
                    timeout=BOTAPP_API_TIMEOUT,
                    **_auth_kwargs(),
                )
        else:
            r = requests.post(
                f"{self.api_url}/bots/",
                data=payload,
                timeout=BOTAPP_API_TIMEOUT,
                **_auth_kwargs(),
            )
            self.bot_instance = r.json()

    def _get_or_create_task(self, func):
        if self.bot_instance is None:
            raise Exception("Bot not set. Call set_bot() first.")

        r = requests.get(
            f"{self.api_url}/tasks/",
            params={'bot': self.bot_instance['id'], 'name': func.__name__},
            timeout=BOTAPP_API_TIMEOUT,
            **_auth_kwargs(),
        )
        tasks = r.json()
        match = next((t for t in tasks if t['name'] == func.__name__), None)

        if match:
            if match['description'] != (func.__doc__ or ''):
                requests.patch(
                    f"{self.api_url}/tasks/{match['id']}/",
                    data={'description': func.__doc__ or ''},
                    timeout=BOTAPP_API_TIMEOUT,
                    **_auth_kwargs(),
                )
            return match
        else:
            payload = {
                'bot': self.bot_instance['id'],
                'name': func.__name__,
                'description': func.__doc__ or '',
            }
            r = requests.post(
                f"{self.api_url}/tasks/",
                data=payload,
                timeout=BOTAPP_API_TIMEOUT,
                **_auth_kwargs(),
            )
            return r.json()

    def task(self, func):
        return task_restful(self, func)
