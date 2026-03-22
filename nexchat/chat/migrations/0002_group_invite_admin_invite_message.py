from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── RoomMember: add is_admin ──────────────────────────────
        migrations.AddField(
            model_name="roommember",
            name="is_admin",
            field=models.BooleanField(default=False),
        ),

        # ── Message: allow blank content (invite messages have no text body) ──
        migrations.AlterField(
            model_name="message",
            name="content",
            field=models.TextField(blank=True),
        ),

        # ── Message: add message_type ─────────────────────────────
        migrations.AddField(
            model_name="message",
            name="message_type",
            field=models.CharField(
                choices=[("text", "Text"), ("invite", "Group Invite")],
                default="text",
                max_length=10,
            ),
        ),

        # ── Message: add metadata JSON ────────────────────────────
        migrations.AddField(
            model_name="message",
            name="metadata",
            field=models.JSONField(blank=True, null=True),
        ),

        # ── GroupInvite: new model ────────────────────────────────
        migrations.CreateModel(
            name="GroupInvite",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(
                    choices=[("pending", "Pending"), ("accepted", "Accepted"), ("declined", "Declined")],
                    default="pending",
                    max_length=10,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("invitee", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="received_invites",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("inviter", models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="sent_invites",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("room", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="invites",
                    to="chat.room",
                )),
            ],
            options={
                "db_table": "chat_group_invite",
                "ordering": ["-created_at"],
                "unique_together": {("room", "invitee")},
            },
        ),
    ]
