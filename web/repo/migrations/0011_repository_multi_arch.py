from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("repo", "0010_build_total_duration_sec"),
    ]

    operations = [
        migrations.AddField(
            model_name="repository",
            name="multi_arch",
            field=models.BooleanField(default=False),
        ),
    ]
