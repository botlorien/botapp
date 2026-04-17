"""Signals do botapp.

Mantém os campos denormalizados de Bot (last_execution_at, last_status)
sincronizados com o TaskLog mais recente. Captura tanto o fluxo standalone
(decorator @task) quanto o plugin (TaskLog criado via REST).

Cuidado: o signal só dispara no processo que salvou o TaskLog. Bots em
modo standalone usam seu próprio processo Django — se estiverem em uma
versão antiga do SDK (sem este signal), o denormalizado drifta. Por isso
existe também `reconcile_bot_last_execution`, chamado periodicamente pelo
`check_alerts` para reparar drift.
"""
import logging

from django.db import connection, transaction
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Bot, TaskLog

logger = logging.getLogger(__name__)


@receiver(post_save, sender=TaskLog)
def update_bot_last_execution(sender, instance, created, **kwargs):
    """Atualiza Bot.last_* com base no TaskLog recém-salvo.

    Só aplica se o log é mais recente que o que está gravado no Bot —
    evita sobrescrever com logs fora de ordem. UPDATE direto no QuerySet
    para não disparar signal do Bot e não carregar o objeto no Python.
    """
    try:
        bot_id = instance.task.bot_id
    except Exception:
        logger.exception("signal: falha ao obter bot_id do TaskLog id=%s", instance.pk)
        return

    try:
        Bot.objects.filter(pk=bot_id).filter(
            Q(last_execution_at__isnull=True) |
            Q(last_execution_at__lte=instance.start_time)
        ).update(
            last_execution_at=instance.start_time,
            last_status=instance.status,
        )
    except Exception:
        logger.exception("signal: falha ao atualizar last_execution do Bot id=%s", bot_id)


def reconcile_bot_last_execution(bot_ids=None):
    """Repara drift entre Bot.last_* e o TaskLog real mais recente.

    Faz um UPDATE ... FROM em SQL puro: para cada bot, calcula o último
    start_time e o status correspondente via DISTINCT ON (Postgres) e
    grava só onde o denormalizado está atrasado. É idempotente e rápido
    (1 query).

    `bot_ids`: restringe o escopo. Se None, processa todos os bots.

    Retorna o número de linhas atualizadas.

    Motivação: o post_save signal só dispara no processo que salvou o log.
    Bots em standalone usando versão antiga do SDK escrevem direto no DB
    sem disparar signal — o Bot denormalizado fica para trás. Esta função
    é chamada pelo scheduler periódico (check_alerts) para self-heal.
    """
    vendor = connection.vendor  # 'postgresql', 'sqlite', ...

    # Postgres: DISTINCT ON é a forma mais eficiente de pegar o último log
    # por bot (1 passagem no índice composto task_id, start_time).
    if vendor == 'postgresql':
        sql = '''
            WITH latest AS (
                SELECT DISTINCT ON (t.bot_id)
                       t.bot_id, tl.start_time, tl.status
                FROM botapp_tasklog tl
                JOIN botapp_task t ON t.id = tl.task_id
                {scope}
                ORDER BY t.bot_id, tl.start_time DESC
            )
            UPDATE botapp_bot b
               SET last_execution_at = latest.start_time,
                   last_status = latest.status
              FROM latest
             WHERE b.id = latest.bot_id
               AND (b.last_execution_at IS NULL
                    OR b.last_execution_at < latest.start_time
                    OR b.last_status IS DISTINCT FROM latest.status)
        '''
        params = []
        scope = ''
        if bot_ids:
            scope = 'WHERE t.bot_id = ANY(%s)'
            params.append(list(bot_ids))
        sql = sql.format(scope=scope)
    else:
        # Fallback SQLite/outros: usa subquery correlata. Mais lento, mas
        # este caminho só existe para dev — em prod temos Postgres.
        sql = '''
            UPDATE botapp_bot
               SET last_execution_at = (
                    SELECT MAX(tl.start_time)
                      FROM botapp_tasklog tl
                      JOIN botapp_task t ON t.id = tl.task_id
                     WHERE t.bot_id = botapp_bot.id
               ),
                   last_status = (
                    SELECT tl.status
                      FROM botapp_tasklog tl
                      JOIN botapp_task t ON t.id = tl.task_id
                     WHERE t.bot_id = botapp_bot.id
                     ORDER BY tl.start_time DESC
                     LIMIT 1
               )
             WHERE EXISTS (
                    SELECT 1 FROM botapp_tasklog tl
                      JOIN botapp_task t ON t.id = tl.task_id
                     WHERE t.bot_id = botapp_bot.id
                       AND (botapp_bot.last_execution_at IS NULL
                            OR botapp_bot.last_execution_at < tl.start_time)
               )
        '''
        params = []
        if bot_ids:
            placeholders = ','.join(['%s'] * len(bot_ids))
            sql += f' AND botapp_bot.id IN ({placeholders})'
            params.extend(bot_ids)

    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount
    except Exception:
        logger.exception("reconcile_bot_last_execution: falha")
        return 0
