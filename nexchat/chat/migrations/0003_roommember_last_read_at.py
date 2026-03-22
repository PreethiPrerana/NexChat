from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0002_group_invite_admin_invite_message'),
    ]

    operations = [
        migrations.AddField(
            model_name='roommember',
            name='last_read_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
