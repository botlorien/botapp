# Generated by Django 5.2 on 2025-04-11 16:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('botapp', '0005_remove_tasklog_os_system_remove_tasklog_pc_path_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tasklog',
            name='env',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='tasklog',
            name='exception_type',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='tasklog',
            name='manual_trigger',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='tasklog',
            name='pid',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tasklog',
            name='python_version',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='tasklog',
            name='trigger_source',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
