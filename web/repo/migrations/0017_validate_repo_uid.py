# Add model-level regex validation for repo_uid.

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("repo", "0016_encrypt_pgp_keys"),
    ]

    operations = [
        migrations.AlterField(
            model_name="repository",
            name="repo_uid",
            field=models.CharField(
                db_index=True,
                max_length=1024,
                unique=True,
                validators=[
                    django.core.validators.RegexValidator(
                        message=(
                            "repo_uid may only contain alphanumeric characters, dots, "
                            "underscores, and hyphens, and must start with an "
                            "alphanumeric character."
                        ),
                        regex="^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
                    )
                ],
            ),
        ),
    ]
