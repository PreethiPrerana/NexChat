"""
ChatConsumer
------------
Handles the full WebSocket lifecycle for a single chat room connection.

Connection flow
  1. Client opens: ws://host/ws/chat/<room_id>/?token=<jwt>
  2. JWTAuthMiddleware validates the token and sets scope["user"].
  3. Consumer verifies membership, then joins the Redis channel group.
  4. Broadcasts join/leave/message events to all members in the group.

Incoming frame types (client → server):
  { "type": "message",  "content": "<text>" }

Outgoing frame types (server → client):
  { "type": "message",  ... }
  { "type": "user_join",  "user": { ... } }
  { "type": "user_leave", "user": { ... } }
  { "type": "error",      "code": "...", "detail": "..." }

NotificationConsumer
--------------------
Per-user channel at ws://host/ws/notifications/?token=<jwt>
Delivers real-time events that are not tied to a specific room:
  { "type": "new_room" }  — a new room (DM or group invite) has been created for this user
"""

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .models import Room, RoomMember, Message


# DB helpers (run in thread pool)

@database_sync_to_async
def get_room(room_id):
    try:
        return Room.objects.get(pk=room_id)
    except Room.DoesNotExist:
        return None


@database_sync_to_async
def is_member(room, user) -> bool:
    return RoomMember.objects.filter(room=room, user=user).exists()


@database_sync_to_async
def save_message(room, user, content: str, reply_to_id=None):
    return Message.objects.select_related("sender", "reply_to__sender").get(
        pk=Message.objects.create(
            room=room, sender=user, content=content, reply_to_id=reply_to_id
        ).pk
    )


@database_sync_to_async
def get_member_ids(room) -> list:
    """Return all user IDs who belong to this room."""
    return list(RoomMember.objects.filter(room=room).values_list("user_id", flat=True))


def _serialise_message(msg: Message) -> dict:
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


# Consumer

class ChatConsumer(AsyncWebsocketConsumer):

    # lifecycle

    async def connect(self):
        user = self.scope["user"]

        # Reject anonymous connections immediately
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

        room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.room = await get_room(room_id)

        if self.room is None:
            await self.close(code=4004)
            return

        if not await is_member(self.room, user):
            await self.close(code=4003)
            return

        # Redis channel group name - one group per room
        self.group_name = f"chat_{self.room.id}"
        self.user = user

        # Join the Redis PubSub group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """Handle an incoming WebSocket frame from the client."""
        try:
            data = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            await self._send_error("invalid_json", "Frame must be valid JSON.")
            return

        msg_type = data.get("type")

        if msg_type == "message":
            await self._handle_message(data)
        else:
            await self._send_error("unknown_type", f"Unknown frame type: {msg_type!r}")

    # incoming frame handlers 

    async def _handle_message(self, data: dict):
        content = (data.get("content") or "").strip()
        if not content:
            await self._send_error("empty_message", "Message content cannot be empty.")
            return
        if len(content) > 4000:
            await self._send_error("too_long", "Message exceeds 4000 characters.")
            return

        reply_to_id = data.get("reply_to_id") or None

        # Persist to DB
        msg = await save_message(self.room, self.user, content, reply_to_id=reply_to_id)
        payload = _serialise_message(msg)

        # Broadcast to all connected room members via channel group
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "broadcast_message", "payload": payload},
        )

        # Also notify every member's personal notification channel so that
        # users who have NOT connected to this room's WebSocket (e.g. they
        # haven't clicked on it yet) still receive an unread-badge update.
        member_ids = await get_member_ids(self.room)
        for uid in member_ids:
            await self.channel_layer.group_send(
                f"user_{uid}",
                {
                    "type": "notify_new_message",
                    "room_id": str(self.room.id),
                    "payload": payload,
                },
            )

    # group event handlers (called by channel layer)
    async def broadcast_message(self, event: dict):
        """Deliver a persisted message to this WebSocket connection."""
        await self.send(text_data=json.dumps(event["payload"]))

    async def broadcast_join(self, event: dict):
        await self.send(text_data=json.dumps({"type": "user_join", "user": event["user"]}))

    async def broadcast_leave(self, event: dict):
        await self.send(text_data=json.dumps({"type": "user_leave", "user": event["user"]}))

    # helpers 
    async def _send_error(self, code: str, detail: str):
        await self.send(text_data=json.dumps({"type": "error", "code": code, "detail": detail}))


# NotificationConsumer 
class NotificationConsumer(AsyncWebsocketConsumer):
    """
    Per-user notification channel: ws://host/ws/notifications/?token=<jwt>

    Clients subscribe on boot and receive a { "type": "new_room" } frame
    whenever a new DM or group invite arrives, prompting them to reload
    their room list without a full page refresh.
    """

    async def connect(self):
        user = self.scope["user"]
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return
        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # Called by channel layer when views.py sends to user_{id}
    async def notify_new_room(self, event):
        await self.send(text_data=json.dumps({"type": "new_room"}))

    async def notify_new_message(self, event):
        """A new message arrived in one of the user's rooms.
        The full message payload is forwarded so the client can append it
        directly — no extra API round-trip needed.
        """
        await self.send(text_data=json.dumps({
            "type": "new_message",
            "room_id": event["room_id"],
            "payload": event.get("payload"),
        }))