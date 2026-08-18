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
        # vindos da integração de CI (ver docs/ci-integration-design.md §7)
        PIPELINE_FAILED = 'pipeline_failed', 'Pipeline falhou'
        PIPELINE_MASKED_ERROR = 'pipeline_masked_error', 'Pipeline verde com erro no log'
        SCHEDULE_WITHOUT_RUN = 'schedule_without_run', 'Agendamento ativo sem execução'
        PROJECT_NEVER_RAN = 'project_never_ran', 'Projeto monitorado sem execução'

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


# ═══════════════════════════════════════════════════════════════════════════
# Integração com servidor de CI (ver docs/ci-integration-design.md)
#
# Estes modelos existem para cobrir o que o SDK não consegue contar: bot que
# morre antes de instrumentar, bot que nunca instrumentou, e pipeline verde cujo
# log tem erro. Tudo GENÉRICO — nenhum default aponta para servidor, grupo ou
# projeto de qualquer organização.
# ═══════════════════════════════════════════════════════════════════════════

class CIConnection(models.Model):
    """Um servidor de CI + namespace a sincronizar.

    O token NÃO fica aqui por padrão: `token_source='env'` guarda apenas o NOME
    da variável de ambiente. Ver o §5 do desenho para o porquê.
    """

    class Kind(models.TextChoices):
        GITLAB = 'gitlab', 'GitLab'

    class TokenSource(models.TextChoices):
        ENV = 'env', 'Variável de ambiente (recomendado)'
        DB = 'db', 'Cifrado no banco'

    class SyncStatus(models.TextChoices):
        OK = 'ok', 'OK'
        ERROR = 'error', 'Erro'
        NEVER = 'never', 'Nunca sincronizado'

    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.GITLAB)
    name = models.CharField(max_length=100, unique=True)
    base_url = models.URLField(
        help_text='URL do servidor de CI. Sem default de propósito.')
    namespace = models.CharField(
        max_length=255,
        help_text='Grupo/organização a sincronizar (path ou id numérico).')

    token_source = models.CharField(max_length=10, choices=TokenSource.choices,
                                    default=TokenSource.ENV)
    token_env_var = models.CharField(
        max_length=100, blank=True, default='BOTAPP_CI_TOKEN',
        help_text='Nome da env var com o token (quando a fonte é ambiente).')
    token_encrypted = models.BinaryField(
        null=True, blank=True, editable=False,
        help_text='Só usado quando a fonte é banco; exige BOTAPP_CI_TOKEN_KEY.')

    enabled = models.BooleanField(default=True, db_index=True)
    discovery_interval_minutes = models.PositiveIntegerField(default=1440)
    poll_interval_minutes = models.PositiveIntegerField(default=15)

    last_discovery_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=10, choices=SyncStatus.choices,
                                        default=SyncStatus.NEVER)
    last_sync_error = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'botapp'
        verbose_name = 'Conexão de CI'
        verbose_name_plural = 'Conexões de CI'

    def __str__(self):
        return f'{self.name} ({self.get_kind_display()})'

    @property
    def token_fingerprint(self):
        """Identifica o token sem revelá-lo — para a tela e para diagnóstico."""
        from .ci_client import resolve_token, fingerprint
        try:
            return fingerprint(resolve_token(self))
        except Exception:
            return ''


class CIProject(models.Model):
    connection = models.ForeignKey(CIConnection, on_delete=models.CASCADE,
                                   related_name='projects')
    external_id = models.BigIntegerField(db_index=True)
    path = models.CharField(max_length=255, db_index=True)
    name = models.CharField(max_length=255)
    web_url = models.URLField(blank=True, default='')
    default_branch = models.CharField(max_length=255, blank=True, default='')
    archived = models.BooleanField(default=False)

    monitored = models.BooleanField(
        default=True, db_index=True,
        help_text='Projeto monitorado tem pipelines sincronizados.')
    scan_logs = models.BooleanField(
        default=False,
        help_text='Procura padrão de erro no log de pipeline BEM-SUCEDIDO '
                  '(detecta "verde que mente"). Custa uma chamada por job.')
    bot = models.ForeignKey(
        Bot, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ci_projects',
        help_text='Vínculo com o bot instrumentado pelo SDK, quando houver.')

    # Arquivamento LOCAL: o projeto continua existindo no servidor de CI, mas
    # deixa de ser sincronizado e de gerar alerta aqui. Serve para repositório
    # dormente, cuja última execução falhou há meses: o alerta é tecnicamente
    # correto e operacionalmente inútil.
    #
    # Não arquiva no servidor de CI de propósito — o cliente é somente-leitura
    # (ver docs/ci-integration-design.md §2). Arquivar lá é ação de quem tem
    # permissão de escrita, feita na interface do próprio CI.
    local_archived = models.BooleanField(default=False, db_index=True)
    local_archived_at = models.DateTimeField(null=True, blank=True)
    local_archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        blank=True, related_name='botapp_archived_ci_projects')
    local_archived_reason = models.CharField(max_length=255, blank=True, default='')

    # cursor do sync incremental — sem ele cada ciclo relê a história inteira
    pipelines_cursor = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True, default='')

    # denormalização p/ a listagem não fazer subquery por linha
    last_pipeline_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_pipeline_status = models.CharField(max_length=20, blank=True, default='',
                                           db_index=True)
    last_pipeline_external_id = models.BigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'botapp'
        verbose_name = 'Projeto de CI'
        verbose_name_plural = 'Projetos de CI'
        unique_together = [('connection', 'external_id')]
        indexes = [
            models.Index(fields=['monitored', '-last_pipeline_at'],
                         name='ciproj_mon_last_idx'),
        ]

    def __str__(self):
        return self.path

    @property
    def inativo(self):
        """Arquivado no servidor de CI ou arquivado localmente."""
        return self.archived or self.local_archived


class CISchedule(models.Model):
    project = models.ForeignKey(CIProject, on_delete=models.CASCADE,
                               related_name='schedules')
    external_id = models.BigIntegerField()
    description = models.CharField(max_length=255, blank=True, default='')
    cron = models.CharField(max_length=100, blank=True, default='')
    cron_timezone = models.CharField(max_length=64, blank=True, default='')
    active = models.BooleanField(default=True, db_index=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    # um agendamento ativo cujo último pipeline é antigo (ou inexistente) é o
    # sintoma de "agendamento que não dispara" — ver alerta schedule_without_run
    last_pipeline_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'botapp'
        verbose_name = 'Agendamento de CI'
        verbose_name_plural = 'Agendamentos de CI'
        unique_together = [('project', 'external_id')]

    def __str__(self):
        return f'{self.project.path} · {self.cron}'


class CIPipeline(models.Model):
    project = models.ForeignKey(CIProject, on_delete=models.CASCADE,
                               related_name='pipelines')
    external_id = models.BigIntegerField(db_index=True)
    iid = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, db_index=True)
    source = models.CharField(max_length=40, blank=True, default='', db_index=True)
    ref = models.CharField(max_length=255, blank=True, default='')
    sha = models.CharField(max_length=64, blank=True, default='')
    commit_title = models.CharField(max_length=255, blank=True, default='')
    web_url = models.URLField(blank=True, default='')
    schedule = models.ForeignKey(CISchedule, on_delete=models.SET_NULL, null=True,
                                blank=True, related_name='pipelines')
    # dado pessoal: controlado por BOTAPP_CI_STORE_TRIGGERED_BY (default ligado)
    triggered_by = models.CharField(max_length=150, blank=True, default='')

    created_at = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)

    # resultado da varredura de log em pipeline verde (§6.3 do desenho)
    log_scanned_at = models.DateTimeField(null=True, blank=True)
    has_masked_error = models.BooleanField(default=False, db_index=True)

    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'botapp'
        verbose_name = 'Pipeline'
        verbose_name_plural = 'Pipelines'
        unique_together = [('project', 'external_id')]
        indexes = [
            models.Index(fields=['-created_at'], name='cipipe_created_desc_idx'),
            models.Index(fields=['project', '-created_at'], name='cipipe_proj_created_idx'),
        ]

    def __str__(self):
        return f'{self.project.path} #{self.external_id} ({self.status})'

    @property
    def is_failure(self):
        return self.status in ('failed', 'canceled')


class CIJob(models.Model):
    pipeline = models.ForeignKey(CIPipeline, on_delete=models.CASCADE,
                                related_name='jobs')
    external_id = models.BigIntegerField(db_index=True)
    name = models.CharField(max_length=255, blank=True, default='')
    stage = models.CharField(max_length=100, blank=True, default='')
    status = models.CharField(max_length=20, db_index=True)
    runner_description = models.CharField(max_length=255, blank=True, default='')
    failure_reason = models.CharField(max_length=100, blank=True, default='')
    web_url = models.URLField(blank=True, default='')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)

    # SÓ a cauda, SÓ em falha/suspeita, com limite de bytes. O log completo não é
    # persistido: trace de CI passa de 1 MB com facilidade (§4 do desenho).
    log_excerpt = models.TextField(blank=True, default='')
    log_excerpt_at = models.DateTimeField(null=True, blank=True)
    matched_pattern = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        app_label = 'botapp'
        verbose_name = 'Job de CI'
        verbose_name_plural = 'Jobs de CI'
        unique_together = [('pipeline', 'external_id')]

    def __str__(self):
        return f'{self.name} ({self.status})'
