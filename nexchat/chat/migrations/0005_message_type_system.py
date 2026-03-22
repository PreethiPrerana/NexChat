from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0004_message_reply_to"),
    ]

    operations = [
        migrations.AlterField(
            model_name="message",
            name="message_type",
            field=models.CharField(
                choices=[
                    ("text", "Text"),
                    ("invite", "Group Invite"),
                    ("system", "System"),
                ],
                default="text",
                max_length=10,
            ),
        ),
    ]
