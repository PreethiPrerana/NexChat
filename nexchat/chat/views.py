"""
Chat REST API views.

All endpoints require JWT authentication (Bearer token).
"""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import GroupInvite, Message, Room, RoomMember
from .serializers import (
    CreateDirectRoomSerializer,
    CreateGroupRoomSerializer,
    GroupInviteSerializer,
    MessageSerializer,
    RoomMemberSerializer,
    RoomSerializer,
)

User = get_user_model()


# ── Internal helpers ──────────────────────────────────────────────

def _serialise_message_payload(msg: Message) -> dict:
    """Build the WebSocket broadcast payload for a message."""
    if msg.sender:
        sender = {
            "id": msg.sender.id,
            "username": msg.sender.username,
            "display_name": msg.sender.get_display_name(),
        }
    else:
        sender = {"id": None, "username": "deleted", "display_name": "Deleted User"}

    reply_to = None
    if msg.reply_to_id:
        r = msg.reply_to
        reply_sender = None
        if r and r.sender:
            reply_sender = {
                "id": r.sender.id,
                "username": r.sender.username,
                "display_name": r.sender.get_display_name(),
            }
        reply_to = {
            "id": str(r.id) if r else None,
            "content": r.content if r else "",
            "message_type": r.message_type if r else "text",
            "sender": reply_sender,
        }

    return {
        "type": "message",
        "message_id": str(msg.id),
        "content": msg.content,
        "reply_to": reply_to,
        "message_type": msg.message_type,
        "metadata": msg.metadata,
        "sender": sender,
        "created_at": msg.created_at.isoformat(),
    }


def _broadcast_to_room(room_id, payload: dict):
    """Push a broadcast_message event to all WebSocket clients in a room.
    For message payloads also send a notify_new_message to every member's
    personal notification channel so unread badges update even when the
    room socket is not open.
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    async_to_sync(channel_layer.group_send)(
        f"chat_{room_id}",
        {"type": "broadcast_message", "payload": payload},
    )
    # Fan out to per-user notification channels for text/invite messages only.
    # System messages (join events etc.) don't need badge notifications.
    if payload.get("type") == "message" and payload.get("message_type") != "system":
        member_ids = RoomMember.objects.filter(room_id=room_id).values_list("user_id", flat=True)
        for uid in member_ids:
            async_to_sync(channel_layer.group_send)(
                f"user_{uid}",
                {"type": "notify_new_message", "room_id": str(room_id), "payload": payload},
            )



def _notify_user_new_room(user_id):
    """Tell a user's notification channel that they have a new room to load."""
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}",
            {"type": "notify_new_room"},
        )


def _send_invite_via_dm(inviter, invitee, group_room: Room, invite: GroupInvite):
    """Create a DM invite message, broadcast it, and notify the invitee."""
    dm_room, _ = Room.get_or_create_direct(inviter, invitee)
    msg = Message.objects.create(
        room=dm_room,
        sender=inviter,
        content="",
        message_type=Message.MessageType.INVITE,
        metadata={
            "invite_id": str(invite.id),
            "group_id": str(group_room.id),
            "group_name": group_room.name,
            "invite_status": GroupInvite.Status.PENDING,
        },
    )
    _broadcast_to_room(dm_room.id, _serialise_message_payload(msg))
    # Tell the invitee to reload their room list so the DM appears immediately
    _notify_user_new_room(invitee.id)


def _require_membership(room_id, user):
    room = get_object_or_404(Room, pk=room_id)
    if not RoomMember.objects.filter(room=room, user=user).exists():
        raise PermissionDenied("You are not a member of this room.")
    return room


def _require_admin(room_id, user):
    room = get_object_or_404(Room, pk=room_id)
    membership = RoomMember.objects.filter(room=room, user=user).first()
    if not membership:
        raise PermissionDenied("You are not a member of this room.")
    if not membership.is_admin:
        raise PermissionDenied("Only admins can perform this action.")
    return room


# ── Room endpoints ────────────────────────────────────────────────

class RoomListCreateView(APIView):
    """
    GET  /api/chat/rooms/  — list rooms the current user belongs to
    POST /api/chat/rooms/  — create a new GROUP room; invites are sent via DM
    """

    def get(self, request):
        room_ids = RoomMember.objects.filter(user=request.user).values_list("room_id", flat=True)
        rooms = (
            Room.objects
            .filter(id__in=room_ids)
            .prefetch_related("members__user")
        )
        return Response(RoomSerializer(rooms, many=True, context={"request": request}).data)

    def post(self, request):
        ser = CreateGroupRoomSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        name = ser.validated_data["name"]
        member_ids = ser.validated_data.get("member_ids", [])

        room = Room.objects.create(
            name=name,
            room_type=Room.RoomType.GROUP,
            created_by=request.user,
        )
        # Creator is always the first admin member
        RoomMember.objects.create(room=room, user=request.user, is_admin=True)

        # For each selected user: create a pending invite and notify via DM
        invited_users = User.objects.filter(id__in=member_ids).exclude(id=request.user.id)
        for invitee in invited_users:
            invite = GroupInvite.objects.create(
                room=room,
                inviter=request.user,
                invitee=invitee,
                status=GroupInvite.Status.PENDING,
            )
            _send_invite_via_dm(request.user, invitee, room, invite)

        return Response(RoomSerializer(room, context={"request": request}).data, status=status.HTTP_201_CREATED)


class DirectRoomView(APIView):
    """
    POST /api/chat/rooms/direct/
    Get or create a DIRECT room between the current user and another user.
    """

    def post(self, request):
        ser = CreateDirectRoomSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        other_user = get_object_or_404(User, pk=ser.validated_data["user_id"])
        if other_user == request.user:
            raise ValidationError({"user_id": "Cannot create a DM with yourself."})

        room, created = Room.get_or_create_direct(request.user, other_user)
        if created:
            # Notify the other user that a new DM has appeared for them
            _notify_user_new_room(other_user.id)
        return Response(RoomSerializer(room, context={"request": request}).data, status=status.HTTP_200_OK)


class RoomDetailView(APIView):
    """GET /api/chat/rooms/<room_id>/"""

    def get(self, request, room_id):
        room = get_object_or_404(Room.objects.prefetch_related("members__user"), pk=room_id)
        if not RoomMember.objects.filter(room=room, user=request.user).exists():
            raise PermissionDenied("You are not a member of this room.")
        return Response(RoomSerializer(room, context={"request": request}).data)


# ── Member endpoints ──────────────────────────────────────────────

class RoomMemberListView(APIView):
    """
    GET  /api/chat/rooms/<room_id>/members/  — list members
    POST /api/chat/rooms/<room_id>/members/  — invite a new member (admin only, sends invite via DM)
    """

    def get(self, request, room_id):
        room = _require_membership(room_id, request.user)
        members = room.members.select_related("user").all()
        return Response(RoomMemberSerializer(members, many=True).data)

    def post(self, request, room_id):
        room = _require_admin(room_id, request.user)
        if room.room_type == Room.RoomType.DIRECT:
            raise ValidationError("Cannot add members to a direct room.")

        user_id = request.data.get("user_id")
        invitee = get_object_or_404(User, pk=user_id)

        if invitee == request.user:
            raise ValidationError({"user_id": "You cannot invite yourself."})
        if RoomMember.objects.filter(room=room, user=invitee).exists():
            return Response({"detail": "Already a member."}, status=status.HTTP_200_OK)

        invite, created = GroupInvite.objects.get_or_create(
            room=room,
            invitee=invitee,
            defaults={"inviter": request.user, "status": GroupInvite.Status.PENDING},
        )
        if not created:
            if invite.status == GroupInvite.Status.PENDING:
                return Response({"detail": "Invite already pending."}, status=status.HTTP_200_OK)
            # Re-invite after a previous decline
            invite.status = GroupInvite.Status.PENDING
            invite.inviter = request.user
            invite.save()

        _send_invite_via_dm(request.user, invitee, room, invite)
        return Response({"detail": "Invite sent."}, status=status.HTTP_201_CREATED)


class RoomMemberDetailView(APIView):
    """
    DELETE /api/chat/rooms/<room_id>/members/<user_id>/  — remove a member (admin only)
    PATCH  /api/chat/rooms/<room_id>/members/<user_id>/  — toggle admin role (admin only)
    """

    def delete(self, request, room_id, user_id):
        room = _require_admin(room_id, request.user)
        if room.room_type == Room.RoomType.DIRECT:
            raise ValidationError("Cannot remove members from a direct room.")
        target = get_object_or_404(User, pk=user_id)
        if target == request.user:
            raise ValidationError({"user_id": "You cannot remove yourself."})
        RoomMember.objects.filter(room=room, user=target).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def patch(self, request, room_id, user_id):
        room = _require_admin(room_id, request.user)
        target = get_object_or_404(User, pk=user_id)
        membership = get_object_or_404(RoomMember, room=room, user=target)
        membership.is_admin = not membership.is_admin
        membership.save()
        return Response(RoomMemberSerializer(membership).data)


# ── Invite endpoints ──────────────────────────────────────────────

class RoomInviteListView(APIView):
    """
    GET /api/chat/rooms/<room_id>/invites/  — list all invites for this room (admin only)
    """

    def get(self, request, room_id):
        _require_admin(room_id, request.user)
        invites = (
            GroupInvite.objects
            .filter(room_id=room_id)
            .select_related("inviter", "invitee")
        )
        return Response(GroupInviteSerializer(invites, many=True).data)


class InviteRespondView(APIView):
    """
    POST /api/chat/invites/<invite_id>/respond/
    Body: { "action": "accept" | "decline" }
    Only the invitee can call this.
    """

    def post(self, request, invite_id):
        invite = get_object_or_404(GroupInvite, pk=invite_id, invitee=request.user)
        if invite.status != GroupInvite.Status.PENDING:
            raise ValidationError("This invite has already been responded to.")

        action = request.data.get("action")
        if action not in ("accept", "decline"):
            raise ValidationError({"action": "Must be 'accept' or 'decline'."})

        if action == "accept":
            invite.status = GroupInvite.Status.ACCEPTED
            invite.save()
            RoomMember.objects.get_or_create(room=invite.room, user=request.user)
            # Persist a system message so the join event appears in history for all members
            sys_msg = Message.objects.create(
                room=invite.room,
                sender=None,
                content=f"{request.user.get_display_name()} joined the group",
                message_type=Message.MessageType.SYSTEM,
            )
            _broadcast_to_room(invite.room_id, _serialise_message_payload(sys_msg))
            room = get_object_or_404(
                Room.objects.prefetch_related("members__user"), pk=invite.room_id
            )
            return Response({"detail": "You joined the group.", "room": RoomSerializer(room, context={"request": request}).data})
        else:
            invite.status = GroupInvite.Status.DECLINED
            invite.save()
            return Response({"detail": "Invite declined."})


# ── Mark read ─────────────────────────────────────────────────────

class MarkReadView(APIView):
    """
    POST /api/chat/rooms/<room_id>/read/
    Update last_read_at for the current user in this room and broadcast
    a read_receipt event so other members can update their UI.
    """

    def post(self, request, room_id):
        room = _require_membership(room_id, request.user)
        membership = RoomMember.objects.get(room=room, user=request.user)

        # Check whether there are actually unread messages to mark.
        # If not, skip the DB write and the WS broadcast entirely.
        unread_qs = room.messages.exclude(sender=request.user).exclude(
            message_type=Message.MessageType.SYSTEM
        )
        if membership.last_read_at:
            unread_qs = unread_qs.filter(created_at__gt=membership.last_read_at)
        if not unread_qs.exists():
            return Response({"detail": "Already up to date."})

        membership.last_read_at = timezone.now()
        membership.save(update_fields=["last_read_at"])

        _broadcast_to_room(room_id, {
            "type": "read_receipt",
            "user_id": request.user.id,
            "read_at": membership.last_read_at.isoformat(),
        })
        return Response({"detail": "Marked as read."})


# ── Message history ───────────────────────────────────────────────

class MessageListView(APIView):
    """
    GET /api/chat/rooms/<room_id>/messages/
    Returns paginated message history, newest-first.

    Query params:
      before  — ISO8601 timestamp; return messages created before this time
      limit   — number of messages (default MESSAGE_PAGE_SIZE, max 100)
    """

    def get(self, request, room_id):
        room = get_object_or_404(Room, pk=room_id)
        membership = RoomMember.objects.filter(room=room, user=request.user).first()
        if not membership:
            raise PermissionDenied("You are not a member of this room.")

        try:
            limit = min(int(request.query_params.get("limit", settings.MESSAGE_PAGE_SIZE)), 100)
        except (ValueError, TypeError):
            limit = settings.MESSAGE_PAGE_SIZE
        before = request.query_params.get("before")

        qs = room.messages.select_related("sender", "reply_to__sender").order_by("-created_at")
        # New members only see messages sent after they joined
        qs = qs.filter(created_at__gte=membership.joined_at)
        if before:
            qs = qs.filter(created_at__lt=before)

        messages = list(reversed(qs[:limit]))
        return Response(MessageSerializer(messages, many=True).data)
