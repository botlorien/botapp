import os
import sys
import socket
import getpass
import platform
import traceback
from functools import wraps
from django.utils import timezone
from .models import Task, TaskLog


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
            log.result_data = {'return': result}
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