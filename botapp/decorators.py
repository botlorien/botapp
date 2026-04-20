import os
import sys
import socket
import getpass
import logging
import platform
import requests
import traceback
from functools import wraps
from datetime import datetime, timezone as _tz
from django.utils import timezone
from requests.auth import HTTPBasicAuth

from .models import Task, TaskLog

logger = logging.getLogger(__name__)

BOTAPP_API_USUARIO = os.environ.get('BOTAPP_API_USUARIO')
BOTAPP_API_SENHA = os.environ.get('BOTAPP_API_SENHA')
BOTAPP_API_TOKEN = os.environ.get('BOTAPP_API_TOKEN')
BOTAPP_API_TIMEOUT = float(os.environ.get('BOTAPP_API_TIMEOUT', '10'))

_BASIC_AUTH_WARNED = False


def _auth_kwargs():
    """Kwargs de auth para requests.*: Token se setado, senão Basic (retrocompat).

    Definido aqui (e reexportado por core_restful) para evitar import
    circular entre core_restful.py e decorators.py — ambos precisam do
    mesmo resolvedor de credencial.
    """
    global _BASIC_AUTH_WARNED

    if BOTAPP_API_TOKEN:
        return {'headers': {'Authorization': f'Token {BOTAPP_API_TOKEN}'}}

    if not _BASIC_AUTH_WARNED:
        logger.warning(
            "botapp SDK usando Basic Auth — método depreciado. "
            "Migre para token: defina BOTAPP_API_TOKEN (gere com "
            "`python manage.py create_bot_token <usuario>` no dashboard). "
            "Basic Auth será removido em uma versão futura."
        )
        _BASIC_AUTH_WARNED = True

    return {'auth': HTTPBasicAuth(BOTAPP_API_USUARIO, BOTAPP_API_SENHA)}


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

        logger.info(
            "task.start bot=%s task=%s log_id=%s host=%s pid=%s env=%s",
            app.bot_instance.name, func.__name__, log.id, host_name, pid, env,
        )

        try:
            result = func(*args, **kwargs)
            log.status = TaskLog.Status.COMPLETED
            log.result_data = {'return': str(result)}
            logger.info(
                "task.success bot=%s task=%s log_id=%s",
                app.bot_instance.name, func.__name__, log.id,
            )
        except Exception as e:
            log.status = TaskLog.Status.FAILED
            log.error_message = traceback.format_exc()
            log.exception_type = type(e).__name__
            logger.exception(
                "task.failed bot=%s task=%s log_id=%s exc=%s",
                app.bot_instance.name, func.__name__, log.id, type(e).__name__,
            )
            raise
        finally:
            log.end_time = timezone.now()
            log.save()
            # Denormalização de Bot.last_* é feita pelo signal post_save em
            # botapp/signals.py (captura tanto @task quanto task_restful).

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
        # UTC-aware: sem offset, DRF com USE_TZ=True interpreta naive como
        # settings.TIME_ZONE (America/Cuiaba), então um container UTC mandava
        # "15:05" e o servidor salvava como 15:05 Cuiaba (19:05 UTC), aparecendo
        # 4h no futuro no dashboard. Com aware UTC o offset viaja no isoformat.
        start_time = datetime.now(_tz.utc)

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

        try:
            log_response = requests.post(
                f"{app.api_url}/tasklog/",
                json=log_payload,
                timeout=BOTAPP_API_TIMEOUT,
                **_auth_kwargs(),
            )
            log = log_response.json()
            log_id = log.get('id')
        except Exception:
            logger.exception("task_restful: falha ao criar TaskLog remoto — execução prossegue sem rastreamento")
            log_id = None

        logger.info(
            "task.start bot=%s task=%s log_id=%s host=%s pid=%s env=%s mode=restful",
            app.bot_instance.get('name'), func.__name__, log_id, host_name, pid, env,
        )

        try:
            result = func(*args, **kwargs)
            status = 'completed'
            result_data = {'return': str(result)}
            error_message = None
            exception_type = None
            logger.info(
                "task.success bot=%s task=%s log_id=%s mode=restful",
                app.bot_instance.get('name'), func.__name__, log_id,
            )
        except Exception as e:
            status = 'failed'
            result_data = None
            error_message = traceback.format_exc()
            exception_type = type(e).__name__
            logger.exception(
                "task.failed bot=%s task=%s log_id=%s exc=%s mode=restful",
                app.bot_instance.get('name'), func.__name__, log_id, exception_type,
            )
            raise
        finally:
            if log_id is not None:
                end_time = datetime.now(_tz.utc)
                patch_payload = {
                    "status": status,
                    "end_time": end_time.isoformat(),
                    "duration": str(end_time - start_time),
                    "result_data": result_data,
                    "error_message": error_message,
                    "exception_type": exception_type
                }
                try:
                    requests.patch(
                        f"{app.api_url}/tasklog/{log_id}/",
                        json=patch_payload,
                        timeout=BOTAPP_API_TIMEOUT,
                        **_auth_kwargs(),
                    )
                except Exception:
                    logger.exception("task_restful: falha ao atualizar TaskLog log_id=%s", log_id)

        return result

    return wrapper