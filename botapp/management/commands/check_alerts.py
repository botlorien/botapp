"""Detecta condições de alerta e cria/dispara notificações.

Regras implementadas:
  - silent_bot          : bot ativo sem execução há mais de N horas
  - error_spike         : bot com ≥ X falhas nos últimos M minutos
  - heartbeat_lost      : log status='started' antigo (execução travada)
  - duration_regression : task com duração média recente acima do SLA

Idempotência: antes de criar um alerta, checa se já existe um ativo
(resolved_at IS NULL) do mesmo type para o mesmo bot. Isso permite
rodar o comando em intervalo curto (ex.: cron a cada 5 min) sem
gerar duplicatas nem flood de notificações.

Uso:
  python manage.py check_alerts               # detecta e dispara
  python manage.py check_alerts --dry-run     # só loga o que faria
  python manage.py check_alerts --no-notify   # cria alertas mas não dispara webhooks

Variáveis de ambiente:
  BOTAPP_SILENT_BOT_THRESHOLD_HOURS        (default 24)
  BOTAPP_ERROR_SPIKE_WINDOW_MINUTES        (default 60)
  BOTAPP_ERROR_SPIKE_THRESHOLD             (default 5)
  BOTAPP_HEARTBEAT_LOST_THRESHOLD_HOURS    (default 6)
  BOTAPP_DURATION_REGRESSION_MULTIPLIER    (default 1.5)
  BOTAPP_DURATION_REGRESSION_WINDOW        (default 20 — últimas N execuções)
"""
import logging
import os
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Q
from django.utils import timezone

from botapp.models import Alert, Bot, Task, TaskLog
from botapp.notifiers import dispatch_alert
from botapp.signals import reconcile_bot_last_execution

logger = logging.getLogger(__name__)


def _severity_for_silent(hours_silent, threshold_hours):
    """Bot mais tempo silencioso = severidade maior.

    Aceita valores fracionários (ex.: threshold de 10 minutos = 0.1667h).
    """
    ratio = hours_silent / max(threshold_hours, 1e-6)
    if ratio >= 4:
        return Alert.Severity.CRITICAL
    if ratio >= 2:
        return Alert.Severity.HIGH
    return Alert.Severity.MEDIUM


def _format_threshold(seconds):
    """Formatação amigável: 600s → '10min', 3600s → '1h', 5400s → '1h30min'."""
    if seconds < 3600:
        return f'{int(round(seconds / 60))}min'
    hours = int(seconds // 3600)
    mins = int(round((seconds % 3600) / 60))
    return f'{hours}h' if mins == 0 else f'{hours}h{mins}min'


def _severity_for_spike(fail_count, threshold):
    ratio = fail_count / max(threshold, 1)
    if ratio >= 4:
        return Alert.Severity.CRITICAL
    if ratio >= 2:
        return Alert.Severity.HIGH
    return Alert.Severity.MEDIUM


class Command(BaseCommand):
    help = 'Detecta bots silenciosos e picos de erro; cria/dispara alertas.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Não cria nem notifica')
        parser.add_argument('--no-notify', action='store_true', help='Cria alertas mas não envia webhooks/email')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        notify = not opts['no_notify']

        default_silent = int(os.environ.get('BOTAPP_SILENT_BOT_THRESHOLD_HOURS', '24'))
        spike_window = int(os.environ.get('BOTAPP_ERROR_SPIKE_WINDOW_MINUTES', '60'))
        spike_threshold = int(os.environ.get('BOTAPP_ERROR_SPIKE_THRESHOLD', '5'))
        hb_threshold = int(os.environ.get('BOTAPP_HEARTBEAT_LOST_THRESHOLD_HOURS', '6'))
        reg_multiplier = float(os.environ.get('BOTAPP_DURATION_REGRESSION_MULTIPLIER', '1.5'))
        reg_window = int(os.environ.get('BOTAPP_DURATION_REGRESSION_WINDOW', '20'))

        now = timezone.now()

        # Repara drift do denormalizado Bot.last_* antes de avaliar regras.
        # Bots em SDK antigo (sem o post_save signal) escrevem TaskLog direto
        # e deixam o Bot desatualizado — o silent_bot mede errado.
        if not dry:
            fixed = reconcile_bot_last_execution()
            if fixed:
                logger.info('check_alerts: reconciled %d bot(s) last_execution_at', fixed)
                self.stdout.write(self.style.NOTICE(
                    f'reconciled {fixed} bot(s) com last_execution_at atrasado.'
                ))

        silent_events = self._detect_silent(now, default_silent, dry)
        spike_events = self._detect_error_spike(now, spike_window, spike_threshold, dry)
        heartbeat_events = self._detect_heartbeat_lost(now, hb_threshold, dry)
        regression_events = self._detect_duration_regression(reg_window, reg_multiplier, dry)
        total = (
            len(silent_events) + len(spike_events)
            + len(heartbeat_events) + len(regression_events)
        )

        if dry:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] {total} alertas seriam criados '
                f'(silent={len(silent_events)}, spike={len(spike_events)}, '
                f'heartbeat={len(heartbeat_events)}, regression={len(regression_events)}).'
            ))
            return

        self.stdout.write(self.style.SUCCESS(f'{total} alertas criados.'))

        if notify:
            for alert in silent_events + spike_events + heartbeat_events + regression_events:
                dispatch_alert(alert)
            self.stdout.write(self.style.SUCCESS(f'{total} alertas despachados.'))

    # ------------------------------------------------------------------
    # Regras
    # ------------------------------------------------------------------
    def _detect_silent(self, now, default_threshold_hours, dry):
        """Bots ativos cujo último log é mais antigo que o threshold.

        Em dry-run retorna uma lista de tuplas (bot_name, message) para contagem;
        em modo real retorna a lista de Alert instances criadas.
        """
        created = []

        # Usa o campo denormalizado Bot.last_execution_at (atualizado pelo signal).
        # Bots que NUNCA executaram (last_execution_at IS NULL) são candidatos
        # somente se foram criados há mais do que o threshold.
        bots = Bot.objects.filter(is_active=True).only(
            'id', 'name', 'last_execution_at',
            'silence_threshold_hours', 'silence_threshold_minutes', 'created_at',
        )

        for bot in bots:
            threshold_seconds = bot.effective_silence_threshold_seconds(default_threshold_hours)
            threshold_hours = threshold_seconds / 3600.0
            cutoff = now - timedelta(seconds=threshold_seconds)

            if bot.last_execution_at is not None:
                if bot.last_execution_at > cutoff:
                    continue
                seconds_silent = (now - bot.last_execution_at).total_seconds()
                last_desc = bot.last_execution_at.isoformat()
            else:
                # Nunca rodou — só alerta se o bot foi criado antes do cutoff
                if bot.created_at and bot.created_at > cutoff:
                    continue
                seconds_silent = (
                    (now - bot.created_at).total_seconds() if bot.created_at else threshold_seconds
                )
                last_desc = 'nunca executou'

            hours_silent = seconds_silent / 3600.0

            # Idempotência: já existe alerta ativo desse tipo para esse bot?
            if Alert.objects.filter(
                bot_id=bot.id, type=Alert.Type.SILENT_BOT, resolved_at__isnull=True,
            ).exists():
                continue

            severity = _severity_for_silent(hours_silent, threshold_hours)
            threshold_label = _format_threshold(threshold_seconds)
            silent_label = _format_threshold(seconds_silent)
            message = (
                f'Bot "{bot.name}" sem execução há {silent_label} '
                f'(threshold: {threshold_label}). Último: {last_desc}.'
            )

            logger.info(
                'alert.detect silent bot=%s silent=%s threshold=%s severity=%s',
                bot.name, silent_label, threshold_label, severity,
            )

            if dry:
                self.stdout.write(f'  [silent_bot] {bot.name} — {message}')
                created.append((bot.name, message))
                continue

            alert = Alert.objects.create(
                bot=bot,
                type=Alert.Type.SILENT_BOT,
                severity=severity,
                message=message,
                payload={
                    'seconds_silent': round(seconds_silent, 1),
                    'hours_silent': round(hours_silent, 2),
                    'threshold_seconds': threshold_seconds,
                    'threshold_hours': round(threshold_hours, 4),
                    'last_execution_at': bot.last_execution_at.isoformat() if bot.last_execution_at else None,
                },
            )
            created.append(alert)

        return created

    def _detect_error_spike(self, now, window_minutes, threshold, dry):
        """Bots com ≥ threshold falhas nos últimos window_minutes."""
        created = []
        since = now - timedelta(minutes=window_minutes)

        # Agrega falhas por bot na janela.
        spikes = (
            TaskLog.objects.filter(
                status=TaskLog.Status.FAILED,
                start_time__gte=since,
            )
            .values('task__bot_id', 'task__bot__name')
            .annotate(fail_count=Count('id'))
            .filter(fail_count__gte=threshold)
        )

        for row in spikes:
            bot_id = row['task__bot_id']
            bot_name = row['task__bot__name']
            fail_count = row['fail_count']

            if Alert.objects.filter(
                bot_id=bot_id, type=Alert.Type.ERROR_SPIKE, resolved_at__isnull=True,
            ).exists():
                continue

            severity = _severity_for_spike(fail_count, threshold)
            message = (
                f'Bot "{bot_name}" acumulou {fail_count} falhas nos últimos '
                f'{window_minutes} minutos (threshold: {threshold}).'
            )

            logger.info(
                'alert.detect spike bot=%s fails=%d window=%d severity=%s',
                bot_name, fail_count, window_minutes, severity,
            )

            if dry:
                self.stdout.write(f'  [error_spike] {bot_name} — {message}')
                created.append((bot_name, message))
                continue

            alert = Alert.objects.create(
                bot_id=bot_id,
                type=Alert.Type.ERROR_SPIKE,
                severity=severity,
                message=message,
                payload={
                    'fail_count': fail_count,
                    'window_minutes': window_minutes,
                    'threshold': threshold,
                },
            )
            created.append(alert)

        return created

    def _detect_heartbeat_lost(self, now, threshold_hours, dry):
        """Logs com status='started' cujo start_time é mais antigo que o threshold.

        Agrega por bot (um alerta por bot mesmo com várias execuções travadas)
        e lista os log_ids no payload para rastreabilidade.
        """
        created = []
        cutoff = now - timedelta(hours=threshold_hours)

        stuck = (
            TaskLog.objects.filter(
                status=TaskLog.Status.STARTED,
                start_time__lt=cutoff,
            )
            .select_related('task', 'task__bot')
            .only('id', 'start_time', 'task__id', 'task__name', 'task__bot__id', 'task__bot__name')
            .order_by('task__bot_id', 'start_time')
        )

        by_bot = {}
        for log in stuck:
            if not log.task_id or not log.task.bot_id:
                continue
            bot_id = log.task.bot_id
            entry = by_bot.setdefault(bot_id, {
                'bot_name': log.task.bot.name,
                'logs': [],
            })
            entry['logs'].append({
                'log_id': log.id,
                'task_id': log.task_id,
                'task_name': log.task.name,
                'start_time': log.start_time.isoformat(),
                'stuck_hours': round((now - log.start_time).total_seconds() / 3600.0, 2),
            })

        for bot_id, info in by_bot.items():
            if Alert.objects.filter(
                bot_id=bot_id, type=Alert.Type.HEARTBEAT_LOST, resolved_at__isnull=True,
            ).exists():
                continue

            logs = info['logs']
            max_stuck = max(e['stuck_hours'] for e in logs)
            severity = _severity_for_silent(max_stuck, threshold_hours)
            count = len(logs)
            message = (
                f'Bot "{info["bot_name"]}" com {count} execução(ões) travada(s) '
                f'(status=started) há mais de {threshold_hours}h. '
                f'Mais antiga: {max_stuck:.1f}h.'
            )

            logger.info(
                'alert.detect heartbeat bot=%s stuck_count=%d max_hours=%.1f severity=%s',
                info['bot_name'], count, max_stuck, severity,
            )

            if dry:
                self.stdout.write(f'  [heartbeat_lost] {info["bot_name"]} — {message}')
                created.append((info['bot_name'], message))
                continue

            alert = Alert.objects.create(
                bot_id=bot_id,
                type=Alert.Type.HEARTBEAT_LOST,
                severity=severity,
                message=message,
                payload={
                    'threshold_hours': threshold_hours,
                    'stuck_count': count,
                    'max_stuck_hours': max_stuck,
                    'logs': logs[:20],  # cap payload
                },
            )
            created.append(alert)

        return created

    def _detect_duration_regression(self, window, multiplier, dry):
        """Tasks cujo SLA (expected_duration_seconds) foi violado na média recente.

        Para cada Task com expected_duration_seconds definido, calcula a duração
        média das últimas `window` execuções completas. Se média ≥ expected * multiplier,
        cria alerta DURATION_REGRESSION (idempotente por bot).
        """
        created = []

        tasks = (
            Task.objects.filter(expected_duration_seconds__isnull=False)
            .select_related('bot')
            .only('id', 'name', 'expected_duration_seconds', 'bot__id', 'bot__name')
        )

        # Agrupa regressões por bot para emitir um único alerta por bot.
        by_bot = {}
        for task in tasks:
            expected = task.expected_duration_seconds
            if not expected or not task.bot_id:
                continue

            recent = (
                TaskLog.objects
                .filter(task_id=task.id, status=TaskLog.Status.COMPLETED, duration__isnull=False)
                .order_by('-start_time')
                .values_list('duration', flat=True)[:window]
            )
            durations = [d.total_seconds() for d in recent if d is not None]
            if len(durations) < max(3, window // 4):
                # amostra insuficiente; evita falso positivo
                continue

            avg = sum(durations) / len(durations)
            threshold_sec = expected * multiplier
            if avg < threshold_sec:
                continue

            entry = by_bot.setdefault(task.bot_id, {
                'bot_name': task.bot.name,
                'tasks': [],
            })
            entry['tasks'].append({
                'task_id': task.id,
                'task_name': task.name,
                'expected_seconds': expected,
                'avg_seconds': round(avg, 2),
                'samples': len(durations),
                'ratio': round(avg / expected, 2),
            })

        for bot_id, info in by_bot.items():
            if Alert.objects.filter(
                bot_id=bot_id, type=Alert.Type.DURATION_REGRESSION, resolved_at__isnull=True,
            ).exists():
                continue

            offenders = info['tasks']
            worst = max(offenders, key=lambda t: t['ratio'])
            severity = (
                Alert.Severity.CRITICAL if worst['ratio'] >= 3
                else Alert.Severity.HIGH if worst['ratio'] >= 2
                else Alert.Severity.MEDIUM
            )
            count = len(offenders)
            message = (
                f'Bot "{info["bot_name"]}" com {count} task(s) acima do SLA. '
                f'Pior: "{worst["task_name"]}" média {worst["avg_seconds"]:.0f}s '
                f'vs esperado {worst["expected_seconds"]}s ({worst["ratio"]}x).'
            )

            logger.info(
                'alert.detect duration_regression bot=%s tasks=%d worst_ratio=%.2f severity=%s',
                info['bot_name'], count, worst['ratio'], severity,
            )

            if dry:
                self.stdout.write(f'  [duration_regression] {info["bot_name"]} — {message}')
                created.append((info['bot_name'], message))
                continue

            alert = Alert.objects.create(
                bot_id=bot_id,
                type=Alert.Type.DURATION_REGRESSION,
                severity=severity,
                message=message,
                payload={
                    'multiplier': multiplier,
                    'window': window,
                    'task_count': count,
                    'tasks': offenders[:20],
                },
            )
            created.append(alert)

        return created
