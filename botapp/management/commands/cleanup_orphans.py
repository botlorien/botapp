"""Marca logs travados (status='started') antigos como failed/orphan_heartbeat.

Muito comum após crashes: o SDK cria o log em status='started' mas a execução
morre antes de escrever o status final. Esses órfãos acumulam e inflam o
detector `heartbeat_lost`. Esta limpeza fecha o log retroativamente com:
    status='failed'
    exception_type='orphan_heartbeat'
    error_message='<contexto>'
    end_time=now, duration=end_time - start_time

Implementação:
- snapshot de ids uma única vez (list)
- processa em lotes pequenos, UMA transação curta por lote
- 1 UPDATE por lote (não 1 por linha) com duration calculado em SQL
- pausa configurável entre lotes para não sufocar o SDK concorrente

Uso:
  python manage.py cleanup_orphans                       # default do env
  python manage.py cleanup_orphans --threshold-hours 12
  python manage.py cleanup_orphans --batch-size 1000 --sleep-ms 50
  python manage.py cleanup_orphans --dry-run
  python manage.py cleanup_orphans --bot-id 42            # escopo um bot

Env vars:
  BOTAPP_ORPHAN_THRESHOLD_HOURS     (default 24)
  BOTAPP_ORPHAN_BATCH_SIZE          (default 500)
  BOTAPP_ORPHAN_SLEEP_MS            (default 100) — entre lotes
"""
import logging
import os
import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import DurationField, ExpressionWrapper, F, Value
from django.utils import timezone

from botapp.models import TaskLog

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = int(os.environ.get('BOTAPP_ORPHAN_BATCH_SIZE', '500'))
DEFAULT_SLEEP_MS = int(os.environ.get('BOTAPP_ORPHAN_SLEEP_MS', '100'))


def cleanup_orphan_heartbeats(
    threshold_hours,
    bot_id=None,
    dry_run=False,
    batch_size=None,
    sleep_ms=None,
    progress_cb=None,
):
    """Fecha logs 'started' antigos em lotes. Retorna o count total atualizado.

    - `batch_size`: linhas por UPDATE. Menor = locks mais curtos, mais round-trips.
    - `sleep_ms`: pausa entre lotes para dar espaço a inserts do SDK.
    - `progress_cb(done, total)`: callback opcional por lote.

    **Retrocompat**: assinatura original `(threshold_hours, bot_id=None, dry_run=False)`
    continua funcionando — novos parâmetros são opcionais com defaults do env.
    """
    if threshold_hours is None or threshold_hours < 1:
        raise ValueError('threshold_hours deve ser um inteiro >= 1')

    batch_size = max(50, int(batch_size if batch_size is not None else DEFAULT_BATCH_SIZE))
    sleep_ms = max(0, int(sleep_ms if sleep_ms is not None else DEFAULT_SLEEP_MS))

    now = timezone.now()
    cutoff = now - timedelta(hours=threshold_hours)

    qs = TaskLog.objects.filter(
        status=TaskLog.Status.STARTED,
        start_time__lt=cutoff,
    )
    if bot_id is not None:
        qs = qs.filter(task__bot_id=bot_id)

    # Snapshot de ids fora de qualquer transação — evita manter um cursor
    # aberto durante a limpeza inteira e permite avançar batch a batch.
    ids = list(qs.values_list('id', flat=True))
    total = len(ids)

    if dry_run or total == 0:
        if progress_cb:
            progress_cb(0, total)
        return total

    message = (
        f'Log marcado como órfão: execução sem finalização há mais de '
        f'{threshold_hours}h (cleanup_orphans).'
    )
    duration_expr = ExpressionWrapper(
        Value(now) - F('start_time'),
        output_field=DurationField(),
    )

    updated = 0
    for i in range(0, total, batch_size):
        chunk = ids[i:i + batch_size]
        # Uma transação curta por lote — libera locks entre lotes. Isso é
        # crítico: a transação inteira anterior mantinha row-locks em milhares
        # de linhas, bloqueando inserts concorrentes do SDK.
        with transaction.atomic():
            n = TaskLog.objects.filter(id__in=chunk).update(
                status=TaskLog.Status.FAILED,
                exception_type='orphan_heartbeat',
                error_message=message,
                end_time=now,
                duration=duration_expr,
            )
        updated += n

        if progress_cb:
            progress_cb(updated, total)

        # Só dorme se ainda tem mais lotes a processar.
        if sleep_ms and (i + batch_size) < total:
            time.sleep(sleep_ms / 1000.0)

    logger.info(
        'cleanup_orphans threshold=%dh bot_id=%s updated=%d batch=%d sleep_ms=%d',
        threshold_hours, bot_id, updated, batch_size, sleep_ms,
    )
    return updated


class Command(BaseCommand):
    help = 'Fecha logs status=started antigos como failed/orphan_heartbeat.'

    def add_arguments(self, parser):
        default = int(os.environ.get('BOTAPP_ORPHAN_THRESHOLD_HOURS', '24'))
        parser.add_argument('--threshold-hours', type=int, default=default,
                            help=f'Horas para considerar órfão (default {default}).')
        parser.add_argument('--bot-id', type=int, default=None,
                            help='Limita a um único bot (default: todos).')
        parser.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE,
                            help=f'Linhas por UPDATE (default {DEFAULT_BATCH_SIZE}).')
        parser.add_argument('--sleep-ms', type=int, default=DEFAULT_SLEEP_MS,
                            help=f'Pausa em ms entre lotes (default {DEFAULT_SLEEP_MS}).')
        parser.add_argument('--dry-run', action='store_true', help='Só conta, não altera.')

    def handle(self, *args, **opts):
        threshold = opts['threshold_hours']
        bot_id = opts['bot_id']
        batch_size = opts['batch_size']
        sleep_ms = opts['sleep_ms']
        dry = opts['dry_run']

        if threshold < 1:
            raise CommandError('--threshold-hours deve ser >= 1')

        def _progress(done, total):
            if total == 0:
                return
            pct = (done * 100) // total
            self.stdout.write(f'  progresso: {done}/{total} ({pct}%)', ending='\r')
            self.stdout.flush()

        count = cleanup_orphan_heartbeats(
            threshold,
            bot_id=bot_id,
            dry_run=dry,
            batch_size=batch_size,
            sleep_ms=sleep_ms,
            progress_cb=None if dry else _progress,
        )

        if dry:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] {count} log(s) seriam marcados como orphan_heartbeat '
                f'(threshold={threshold}h, bot_id={bot_id}).'
            ))
        else:
            self.stdout.write('')  # quebra a linha do progresso
            self.stdout.write(self.style.SUCCESS(
                f'{count} log(s) marcados como orphan_heartbeat '
                f'(threshold={threshold}h, bot_id={bot_id}, batch={batch_size}, sleep={sleep_ms}ms).'
            ))
