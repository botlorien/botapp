from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('botapp', '0010_alerts'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='expected_duration_seconds',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
