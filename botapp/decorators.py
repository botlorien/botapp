import os
import sys
import socket
import getpass
import platform
import requests
import traceback
from functools import wraps
from datetime import datetime
from django.utils import timezone
from requests.auth import HTTPBasicAuth

from .models import Task, TaskLog

BOTAPP_API_USUARIO = os.environ.get('BOTAPP_API_USUARIO')
BOTAPP_API_SENHA = os.environ.get('BOTAPP_API_SENHA')


def task(app, func=None):
    if func is None:
        return lambda f: task(app, f)

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not app.bot_instance:
            raise Exception("Bot não foi definido. Use app.set_bot(...) antes de declarar tarefas.")
        if not app.bot_instance.is_active:
            raise Exception(f"❌ O bot '{app.bot_instance.name}' está inativo e não pode executar tarefas.")

        # Coleta de informações do ambiente
        try:
            host_name = socket.gethostname()
            host_ip = socket.gethostbyname(host_name)
        except:
            host_name = None
            host_ip = None

        try:
            user_login = getpass.getuser()
        except:
            user_login = None

        try:
            bot_dir = os.getcwd()
        except:
            bot_dir = None

        try:
            os_platform = platform.platform()
        except:
            os_platform = None

        try:
            python_version = platform.python_version()
        except:
            python_version = None

        pid = os.getpid()
        env = os.environ.get('BOTAPP_DEPLOY_ENV', 'dev')
        trigger_source = "cli"
        manual_trigger = True

        task_obj = app._get_or_create_task(func)

        log = TaskLog.objects.create(
            task=task_obj,
            status=TaskLog.Status.STARTED,
            start_time=timezone.now(),
            host_ip=host_ip,
            host_name=host_name,
            user_login=user_login,
            bot_dir=bot_dir,
            os_platform=os_platform,
            python_version=python_version,
            pid=pid,
            env=env,
            trigger_source=trigger_source,
            manual_trigger=manual_trigger
        )

        try:
            result = func(*args, **kwargs)
            log.status = TaskLog.Status.COMPLETED
            log.result_data = {'return': str(result)}
        except Exception as e:
            log.status = TaskLog.Status.FAILED
            log.error_message = traceback.format_exc()
            log.exception_type = type(e).__name__  # 👈 Aqui
            raise
        finally:
            log.end_time = timezone.now()
            log.save()

        return result

    return wrapper

def task_restful(app, func=None):
    if func is None:
        return lambda f: task_restful(app, f)

    @wraps(func)
    def wrapper(*args, **kwargs):
        app.bot_instance = app.search_bot(app.bot_name)
        if not app.bot_instance:
            raise Exception("Bot não foi definido. Use app.set_bot(...) antes de declarar tarefas.")
        if not app.bot_instance.get('is_active', True):
            raise Exception(f"❌ O bot '{app.bot_instance['name']}' está inativo e não pode executar tarefas.")

        # Coleta de informações do ambiente
        def safe(fn):
            try:
                return fn()
            except:
                return None

        host_name = safe(socket.gethostname)
        host_ip = safe(lambda: socket.gethostbyname(host_name or 'localhost'))
        user_login = safe(getpass.getuser)
        bot_dir = safe(os.getcwd)
        os_platform = safe(platform.platform)
        python_version = safe(platform.python_version)
        pid = os.getpid()
        env = os.environ.get('BOTAPP_DEPLOY_ENV', 'dev')
        trigger_source = "cli"
        manual_trigger = True

        task_obj = app._get_or_create_task(func)
        start_time = datetime.now()

        # Cria o log via API
        log_payload = {
            "task": task_obj['id'],
            "status": "started",
            "start_time": start_time.isoformat(),
            "host_ip": host_ip,
            "host_name": host_name,
            "user_login": user_login,
            "bot_dir": bot_dir,
            "os_platform": os_platform,
            "python_version": python_version,
            "pid": pid,
            "env": env,
            "trigger_source": trigger_source,
            "manual_trigger": manual_trigger
        }

        log_response = requests.post(f"{app.api_url}/tasklog/", json=log_payload, auth=HTTPBasicAuth(BOTAPP_API_USUARIO, BOTAPP_API_SENHA))
        log = log_response.json()
        log_id = log.get('id')

        try:
            result = func(*args, **kwargs)
            status = 'completed'
            result_data = {'return': str(result)}
            error_message = None
            exception_type = None
        except Exception as e:
            status = 'failed'
            result_data = None
            error_message = traceback.format_exc()
            exception_type = type(e).__name__
            raise
        finally:
            end_time = datetime.now()
            patch_payload = {
                "status": status,
                "end_time": end_time.isoformat(),
                "duration": str(end_time - start_time),
                "result_data": result_data,
                "error_message": error_message,
                "exception_type": exception_type
            }
            try:
                requests.patch(f"{app.api_url}/tasklog/{log_id}/", json=patch_payload, auth=HTTPBasicAuth(BOTAPP_API_USUARIO, BOTAPP_API_SENHA))
            except Exception as e:
                print(f"⚠️ Falha ao atualizar TaskLog: {e}")

        return result

    return wrapper