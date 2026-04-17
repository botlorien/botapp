"""Denormaliza último status/execução em Bot para eliminar Subquery correlata.

Retrocompatível: campos nullable. Backfill roda em lote (1 UPDATE por bot com
`distinct on` no Postgres, fallback ORM em outros bancos).
"""
from django.db import migrations, models


def backfill_last_execution(apps, schema_editor):
    Bot = apps.get_model('botapp', 'Bot')
    Task = apps.get_model('botapp', 'Task')
    TaskLog = apps.get_model('botapp', 'TaskLog')

    vendor = schema_editor.connection.vendor
    bot_tbl = Bot._meta.db_table
    task_tbl = Task._meta.db_table
    log_tbl = TaskLog._meta.db_table

    if vendor == 'postgresql':
        # Postgres: 1 query usando DISTINCT ON no último log por bot.
        # Nomes de tabela vêm de _meta.db_table — respeitam qualquer prefixo
        # customizado que o Django adicione (ex.: botapp_bot).
        sql = f"""
            UPDATE "{bot_tbl}" b
            SET last_execution_at = latest.start_time,
                last_status = latest.status
            FROM (
                SELECT DISTINCT ON (t.bot_id)
                    t.bot_id,
                    l.start_time,
                    l.status
                FROM "{log_tbl}" l
                JOIN "{task_tbl}" t ON t.id = l.task_id
                ORDER BY t.bot_id, l.start_time DESC
            ) latest
            WHERE b.id = latest.bot_id;
        """
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(sql)
    else:
        # Fallback portável (1 query por bot). OK para bancos pequenos.
        for bot in Bot.objects.all().iterator():
            last = (
                TaskLog.objects.filter(task__bot_id=bot.id)
                .order_by('-start_time')
                .values('start_time', 'status')
                .first()
            )
            if last:
                Bot.objects.filter(pk=bot.pk).update(
                    last_execution_at=last['start_time'],
                    last_status=last['status'],
                )


def noop_reverse(apps, schema_editor):
    # Rollback não precisa fazer nada — os campos serão removidos pela
    # operação RemoveField que o Django gera automaticamente.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('botapp', '0008_indexes_performance'),
    ]

    operations = [
        migrations.AddField(
            model_name='bot',
            name='last_execution_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='bot',
            name='last_status',
            field=models.CharField(blank=True, db_index=True, max_length=20, null=True),
        ),
        migrations.AddIndex(
            model_name='bot',
            index=models.Index(fields=['-last_execution_at'], name='bot_last_exec_desc_idx'),
        ),
        migrations.AddIndex(
            model_name='bot',
            index=models.Index(
                fields=['last_status', '-last_execution_at'],
                name='bot_last_status_idx',
            ),
        ),
        migrations.RunPython(backfill_last_execution, noop_reverse),
    ]
