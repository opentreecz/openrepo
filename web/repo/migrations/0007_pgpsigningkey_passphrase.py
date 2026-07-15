from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('repo', '0006_uploadtask'),
    ]

    operations = [
        migrations.AddField(
            model_name='pgpsigningkey',
            name='passphrase',
            field=models.CharField(blank=True, default='', max_length=65536),
        ),
    ]
