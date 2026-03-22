from rest_framework import serializers
from accounts.serializers import UserSerializer
from .models import GroupInvite, Message, Room, RoomMember


class RoomMemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = RoomMember
        fields = ("user", "joined_at", "is_admin")


class RoomSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    member_count = serializers.SerializerMethodField()
    members_detail = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Room
        fields = ("id", "name", "room_type", "created_by", "member_count", "members_detail", "unread_count", "created_at")
        read_only_fields = ("id", "room_type", "created_by", "member_count", "members_detail", "unread_count", "created_at")

    def get_member_count(self, obj) -> int:
        return obj.members.count()

    def get_members_detail(self, obj):
        # Uses prefetch_related("members__user") from the view for efficiency
        return [
            {
                "id": m.user.id,
                "username": m.user.username,
                "display_name": m.user.get_display_name(),
                "is_admin": m.is_admin,
                "last_read_at": m.last_read_at.isoformat() if m.last_read_at else None,
            }
            for m in obj.members.all()
        ]

    def get_unread_count(self, obj) -> int:
        request = self.context.get("request")
        if not request:
            return 0
        user_id = request.user.id
        for m in obj.members.all():
            if m.user_id == user_id:
                qs = obj.messages.exclude(
                    sender_id=user_id
                ).exclude(message_type=Message.MessageType.SYSTEM)
                if m.last_read_at:
                    qs = qs.filter(created_at__gt=m.last_read_at)
                return qs.count()
        return 0


class CreateGroupRoomSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    member_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
        max_length=49,
        help_text="User IDs to invite (invites sent via DM; creator is added directly).",
    )


class CreateDirectRoomSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(help_text="The other user's ID.")


class ReplyPreviewSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)

    class Meta:
        model = Message
        fields = ("id", "content", "message_type", "sender")


class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    reply_to = ReplyPreviewSerializer(read_only=True)
    metadata = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ("id", "room", "sender", "content", "reply_to", "message_type", "metadata", "created_at")
        read_only_fields = ("id", "room", "sender", "created_at")

    def get_metadata(self, obj):
        """For invite messages, inject the current invite status into metadata."""
        if obj.message_type != Message.MessageType.INVITE or not obj.metadata:
            return obj.metadata
        invite_id = obj.metadata.get("invite_id")
        if not invite_id:
            return obj.metadata
        try:
            invite = GroupInvite.objects.get(pk=invite_id)
            return {**obj.metadata, "invite_status": invite.status}
        except GroupInvite.DoesNotExist:
            return {**obj.metadata, "invite_status": "expired"}


class GroupInviteSerializer(serializers.ModelSerializer):
    room_id = serializers.UUIDField(source="room.id", read_only=True)
    room_name = serializers.CharField(source="room.name", read_only=True)
    inviter = UserSerializer(read_only=True)
    invitee = UserSerializer(read_only=True)

    class Meta:
        model = GroupInvite
        fields = ("id", "room_id", "room_name", "inviter", "invitee", "status", "created_at", "updated_at")
        read_only_fields = fields
