import django.db.models.deletion
from django.db import migrations, models


def migrate_keep_only_latest(apps, schema_editor):
    """Convert keep_only_latest=True to retention_policy=keep_latest_n / count=1."""
    Repository = apps.get_model("repo", "Repository")
    Repository.objects.filter(keep_only_latest=True).update(
        retention_policy="keep_latest_n",
        retention_keep_count=1,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("repo", "0011_repository_multi_arch"),
    ]

    operations = [
        migrations.AddField(
            model_name="repository",
            name="retention_policy",
            field=models.CharField(
                choices=[
                    ("none", "Keep everything"),
                    ("keep_latest_n", "Keep latest N versions"),
                    ("max_age_days", "Delete packages older than N days"),
                    ("keep_latest_n_and_age", "Keep latest N versions AND delete older than N days"),
                ],
                db_index=True,
                default="none",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="repository",
            name="retention_keep_count",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="repository",
            name="retention_max_age_days",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(migrate_keep_only_latest, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="repository",
            name="keep_only_latest",
        ),
    ]
