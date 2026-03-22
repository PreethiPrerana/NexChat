import uuid
from django.conf import settings
from django.db import models


class Room(models.Model):
    class RoomType(models.TextChoices):
        GROUP = "group", "Group"
        DIRECT = "direct", "Direct"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, blank=True)
    room_type = models.CharField(max_length=10, choices=RoomType.choices, default=RoomType.GROUP)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_rooms",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_room"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or f"DM-{self.id}"

    @classmethod
    def get_or_create_direct(cls, user_a, user_b):
        rooms_a = set(RoomMember.objects.filter(user=user_a).values_list("room_id", flat=True))
        rooms_b = set(RoomMember.objects.filter(user=user_b).values_list("room_id", flat=True))
        shared = rooms_a & rooms_b
        direct = cls.objects.filter(id__in=shared, room_type=cls.RoomType.DIRECT).first()
        if direct:
            return direct, False
        room = cls.objects.create(room_type=cls.RoomType.DIRECT, created_by=user_a)
        RoomMember.objects.bulk_create([
            RoomMember(room=room, user=user_a),
            RoomMember(room=room, user=user_b),
        ])
        return room, True


class RoomMember(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="room_memberships",
    )
    is_admin = models.BooleanField(default=False)
    last_read_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_room_member"
        unique_together = ("room", "user")
        ordering = ["joined_at"]

    def __str__(self):
        return f"{self.user.username} in {self.room}"


class Message(models.Model):
    class MessageType(models.TextChoices):
        TEXT = "text", "Text"
        INVITE = "invite", "Group Invite"
        SYSTEM = "system", "System"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="messages",
    )
    content = models.TextField(blank=True)
    reply_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replies",
    )
    message_type = models.CharField(
        max_length=10, choices=MessageType.choices, default=MessageType.TEXT
    )
    metadata = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_message"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender} → {self.room} @ {self.created_at:%H:%M}"


class GroupInvite(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="invites")
    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_invites",
    )
    invitee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_invites",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "chat_group_invite"
        unique_together = ("room", "invitee")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invite: {self.invitee} → {self.room} ({self.status})"
