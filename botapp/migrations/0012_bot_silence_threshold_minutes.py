from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('botapp', '0011_task_expected_duration_seconds'),
    ]

    operations = [
        migrations.AddField(
            model_name='bot',
            name='silence_threshold_minutes',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
