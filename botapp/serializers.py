# botapp/serializers.py

from rest_framework import serializers
from .models import Alert, Bot, Task, TaskLog


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


class AlertIngestSerializer(serializers.Serializer):
    """Valida um alerta recebido de um monitor externo (ex.: webhook do Grafana).

    Não é um ModelSerializer: a entrada não espelha o model 1:1. `status`
    controla criar-vs-resolver, `fingerprint` é a chave de deduplicação e vai
    guardada dentro do `payload` (o model não tem coluna própria — a dedup segue
    o mesmo padrão de `payload__project_id` já usado pela integração de CI, sem
    exigir migração de schema). `type` é livre de propósito: este é um pacote
    genérico e não deve embutir a taxonomia de alertas de nenhum consumidor.
    """

    STATUS_CHOICES = ('firing', 'resolved')

    status = serializers.ChoiceField(
        choices=STATUS_CHOICES, default='firing', required=False,
    )
    type = serializers.CharField(max_length=30)
    severity = serializers.ChoiceField(
        choices=Alert.Severity.values, default=Alert.Severity.MEDIUM, required=False,
    )
    message = serializers.CharField()
    fingerprint = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default='',
    )
    bot_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default='',
    )
    payload = serializers.JSONField(required=False, default=dict)

    def validate_payload(self, value):
        # payload precisa ser um objeto JSON (dict) — a dedup por fingerprint e
        # o render no dashboard assumem um mapa, não uma lista/escalar.
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('payload deve ser um objeto JSON.')
        return value
