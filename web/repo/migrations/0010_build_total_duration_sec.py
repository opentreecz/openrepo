from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('repo', '0009_alter_repository_promote_to'),
    ]

    operations = [
        migrations.AddField(
            model_name='build',
            name='total_duration_sec',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
