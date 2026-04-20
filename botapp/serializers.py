# botapp/serializers.py

from rest_framework import serializers
from .models import Bot, Task, TaskLog


# Listar campos explicitamente evita dois problemas:
#   1. Vazamento de campos novos adicionados no model (regressão silenciosa).
#   2. Mass-assignment: clientes mandando campos que não deveriam poder setar.
# A lista espelha exatamente o que os SDKs (Python BotAppRestful e Go client)
# consomem hoje — alterações aqui são breaking change para os RPAs.


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = (
            'id',
            'bot',
            'name',
            'description',
            'expected_duration_seconds',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


class BotSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(many=True, read_only=True)

    class Meta:
        model = Bot
        fields = (
            'id',
            'name',
            'description',
            'version',
            'department',
            'is_active',
            'silence_threshold_hours',
            'silence_threshold_minutes',
            'last_execution_at',
            'last_status',
            'created_at',
            'updated_at',
            'tasks',
        )
        read_only_fields = (
            'id',
            'last_execution_at',
            'last_status',
            'created_at',
            'updated_at',
        )


class TaskLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskLog
        fields = (
            'id',
            'task',
            'status',
            'start_time',
            'end_time',
            'duration',
            'result_data',
            'error_message',
            'exception_type',
            'bot_dir',
            'os_platform',
            'python_version',
            'host_ip',
            'host_name',
            'user_login',
            'pid',
            'manual_trigger',
            'trigger_source',
            'env',
        )
        read_only_fields = ('id',)
