# Generated migration to add Alpine APK repo type choice.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("repo", "0014_allow_multiple_promote_to"),
    ]

    operations = [
        migrations.AlterField(
            model_name="repository",
            name="repo_type",
            field=models.CharField(
                choices=[
                    ("deb", "Debian/APT"),
                    ("rpm", "Red Hat/RPM"),
                    ("apk", "Alpine/APK"),
                    ("files", "Generic Files"),
                ],
                db_index=True,
                default="deb",
                max_length=128,
            ),
        ),
    ]
