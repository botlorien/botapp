from django.conf import settings
from django.db import models
from django.utils import timezone


class Bot(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    description = models.TextField()
    version = models.CharField(max_length=50)
    department = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Denormalização para evitar Subquery correlata ao listar bots.
    # Atualizados pelo decorator @task em cada execução. Nullable para bots
    # que nunca rodaram. Permite consultas O(1) como "bots silenciosos há N dias".
    last_execution_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_status = models.CharField(max_length=20, null=True, blank=True, db_index=True)

    # Override por bot do threshold global de silêncio (em horas). Null = usa
    # BOTAPP_SILENT_BOT_THRESHOLD_HOURS do ambiente. Permite bots críticos
    # alertarem mais cedo e bots raros alertarem mais tarde.
    silence_threshold_hours = models.PositiveIntegerField(null=True, blank=True)
    # Alternativa mais granular para bots que rodam em intervalos curtos
    # (ex.: a cada 10 min). Se setado, tem precedência sobre silence_threshold_hours.
    silence_threshold_minutes = models.PositiveIntegerField(null=True, blank=True)

    def effective_silence_threshold_seconds(self, default_hours):
        """Retorna o threshold efetivo em segundos. Precedência: minutos > horas > default."""
        if self.silence_threshold_minutes:
            return self.silence_threshold_minutes * 60
        if self.silence_threshold_hours:
            return self.silence_threshold_hours * 3600
        return int(default_hours) * 3600

    class Meta:
        app_label = 'botapp'
        verbose_name = "Bot"
        verbose_name_plural = "Bots"
        indexes = [
            models.Index(fields=['department', 'is_active'], name='bot_dept_active_idx'),
            models.Index(fields=['-updated_at'], name='bot_updated_desc_idx'),
            models.Index(fields=['-last_execution_at'], name='bot_last_exec_desc_idx'),
            models.Index(fields=['last_status', '-last_execution_at'], name='bot_last_status_idx'),
        ]

    def __str__(self):
        return self.name


class Task(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name='tasks')
    name = models.CharField(max_length=255, db_index=True)
    description = models.TextField(blank=True)
    expected_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'botapp'
        verbose_name = "Tarefa"
        verbose_name_plural = "Tarefas"
        indexes = [
            models.Index(fields=['bot', 'name']),
        ]

    def __str__(self):
        return self.name


class TaskLog(models.Model):
    class Status(models.TextChoices):
        STARTED = 'started'
        COMPLETED = 'completed'
        FAILED = 'failed'

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='logs')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STARTED, db_index=True)
    result_data = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    exception_type = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    start_time = models.DateTimeField(default=timezone.now, db_index=True)
    end_time = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)
    bot_dir = models.CharField(max_length=255, blank=True, null=True)
    os_platform = models.CharField(max_length=255, blank=True, null=True)
    python_version = models.CharField(max_length=50, null=True, blank=True)
    host_ip = models.GenericIPAddressField(null=True, blank=True)
    host_name = models.CharField(max_length=255, null=True, blank=True)
    user_login = models.CharField(max_length=150, null=True, blank=True)
    pid = models.IntegerField(null=True, blank=True)
    manual_trigger = models.BooleanField(default=False)
    trigger_source = models.CharField(max_length=100, null=True, blank=True)
    env = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        app_label = 'botapp'
        verbose_name = "Log de Tarefa"
        verbose_name_plural = "Logs de Tarefas"
        indexes = [
            models.Index(fields=['-start_time'], name='tasklog_start_time_desc_idx'),
            models.Index(fields=['task', '-start_time'], name='tasklog_task_start_idx'),
            models.Index(fields=['status', '-start_time'], name='tasklog_status_start_idx'),
            models.Index(fields=['env', '-start_time'], name='tasklog_env_start_idx'),
        ]

    def save(self, *args, **kwargs):
        if self.start_time and self.end_time:
            self.duration = self.end_time - self.start_time
        super().save(*args, **kwargs)


class Alert(models.Model):
    """Alerta gerado pelo monitoramento — bot silencioso, pico de erros, etc.

    Um alerta é *ativo* enquanto `resolved_at` for NULL. O comando
    `check_alerts` é idempotente: não cria novo alerta se já existe um ativo
    do mesmo `type` para o mesmo `bot`.
    """

    class Type(models.TextChoices):
        SILENT_BOT = 'silent_bot', 'Bot silencioso'
        ERROR_SPIKE = 'error_spike', 'Pico de erros'
        HEARTBEAT_LOST = 'heartbeat_lost', 'Heartbeat perdido'
        DURATION_REGRESSION = 'duration_regression', 'Regressão de duração'

    class Severity(models.TextChoices):
        LOW = 'low', 'Baixa'
        MEDIUM = 'medium', 'Média'
        HIGH = 'high', 'Alta'
        CRITICAL = 'critical', 'Crítica'

    type = models.CharField(max_length=30, choices=Type.choices, db_index=True)
    severity = models.CharField(
        max_length=10, choices=Severity.choices, default=Severity.MEDIUM, db_index=True,
    )
    bot = models.ForeignKey(
        Bot, on_delete=models.CASCADE, related_name='alerts', null=True, blank=True,
    )
    message = models.TextField()
    payload = models.JSONField(null=True, blank=True)  # contexto: últimas N falhas, threshold, etc.

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    acked_at = models.DateTimeField(null=True, blank=True)
    acked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='botapp_acked_alerts',
    )
    resolved_at = models.DateTimeField(null=True, blank=True, db_index=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='botapp_resolved_alerts',
    )
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'botapp'
        verbose_name = 'Alerta'
        verbose_name_plural = 'Alertas'
        indexes = [
            models.Index(fields=['-created_at'], name='alert_created_desc_idx'),
            models.Index(fields=['bot', 'type', 'resolved_at'], name='alert_bot_type_res_idx'),
        ]

    def __str__(self):
        target = self.bot.name if self.bot_id else 'global'
        return f'[{self.severity}] {self.type} · {target}'

    @property
    def is_active(self):
        return self.resolved_at is None
