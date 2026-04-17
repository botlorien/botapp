"""Performance indexes — retrocompatível, apenas adiciona índices/db_index.

Safe to run em banco com dados históricos; não remove nem altera colunas.
"""
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('botapp', '0007_alter_bot_options_alter_task_options_and_more'),
    ]

    operations = [
        # Bot — db_index em campos muito filtrados
        migrations.AlterField(
            model_name='bot',
            name='name',
            field=models.CharField(db_index=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='bot',
            name='department',
            field=models.CharField(blank=True, db_index=True, max_length=100, null=True),
        ),
        migrations.AlterField(
            model_name='bot',
            name='is_active',
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.AddIndex(
            model_name='bot',
            index=models.Index(fields=['department', 'is_active'], name='bot_dept_active_idx'),
        ),
        migrations.AddIndex(
            model_name='bot',
            index=models.Index(fields=['-updated_at'], name='bot_updated_desc_idx'),
        ),

        # Task — db_index e composto
        migrations.AlterField(
            model_name='task',
            name='name',
            field=models.CharField(db_index=True, max_length=255),
        ),
        migrations.AddIndex(
            model_name='task',
            index=models.Index(fields=['bot', 'name'], name='botapp_task_bot_id_c48502_idx'),
        ),

        # TaskLog — índices críticos para dashboard/listagem
        migrations.AlterField(
            model_name='tasklog',
            name='status',
            field=models.CharField(
                choices=[
                    ('started', 'Started'),
                    ('completed', 'Completed'),
                    ('failed', 'Failed'),
                ],
                db_index=True,
                default='started',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='tasklog',
            name='exception_type',
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='tasklog',
            name='start_time',
            field=models.DateTimeField(db_index=True, default=django.utils.timezone.now),
        ),
        migrations.AddIndex(
            model_name='tasklog',
            index=models.Index(fields=['-start_time'], name='tasklog_start_time_desc_idx'),
        ),
        migrations.AddIndex(
            model_name='tasklog',
            index=models.Index(fields=['task', '-start_time'], name='tasklog_task_start_idx'),
        ),
        migrations.AddIndex(
            model_name='tasklog',
            index=models.Index(fields=['status', '-start_time'], name='tasklog_status_start_idx'),
        ),
        migrations.AddIndex(
            model_name='tasklog',
            index=models.Index(fields=['env', '-start_time'], name='tasklog_env_start_idx'),
        ),
    ]
