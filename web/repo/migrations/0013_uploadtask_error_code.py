from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("repo", "0012_retention_policy"),
    ]

    operations = [
        migrations.AddField(
            model_name="uploadtask",
            name="error_code",
            field=models.CharField(
                blank=True,
                default="",
                max_length=64,
                help_text="Machine-readable error code when status='failed' (e.g. 'PACKAGE_EXISTS').",
            ),
        ),
    ]
