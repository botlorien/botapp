from django.db import models
from django.utils import timezone


class Bot(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField()
    version = models.CharField(max_length=50)
    department = models.CharField(max_length=100, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Bot"
        verbose_name_plural = "Bots"

    def __str__(self):
        return self.name


class Task(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name='tasks')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tarefa"
        verbose_name_plural = "Tarefas"

    def __str__(self):
        return self.name


class TaskLog(models.Model):
    class Status(models.TextChoices):
        STARTED = 'started'
        COMPLETED = 'completed'
        FAILED = 'failed'

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='logs')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STARTED)
    result_data = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    exception_type = models.CharField(max_length=255, null=True, blank=True)
    start_time = models.DateTimeField(default=timezone.now)
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
        verbose_name = "Log de Tarefa"
        verbose_name_plural = "Logs de Tarefas"

    def save(self, *args, **kwargs):
        if self.start_time and self.end_time:
            self.duration = self.end_time - self.start_time
        super().save(*args, **kwargs)
