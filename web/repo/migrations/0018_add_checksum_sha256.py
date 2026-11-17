# Add checksum_sha256 to Package and sha256 to UploadTask (Phase 4.6).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("repo", "0017_validate_repo_uid"),
    ]

    operations = [
        migrations.AddField(
            model_name="package",
            name="checksum_sha256",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="uploadtask",
            name="sha256",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
