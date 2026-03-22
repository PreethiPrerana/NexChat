from django.urls import path
from .views import (
    RoomListCreateView,
    DirectRoomView,
    RoomDetailView,
    RoomMemberListView,
    RoomMemberDetailView,
    RoomInviteListView,
    InviteRespondView,
    MarkReadView,
    MessageListView,
)

urlpatterns = [
    # GET — list my rooms
    # POST — create group room (invites sent via DM)
    path("rooms/", RoomListCreateView.as_view(), name="room-list-create"),

    # POST — get or create DM
    path("rooms/direct/", DirectRoomView.as_view(), name="room-direct"),

    # GET — room detail
    path("rooms/<uuid:room_id>/", RoomDetailView.as_view(), name="room-detail"),

    # GET — list members
    # POST — invite a member (admin only)
    path("rooms/<uuid:room_id>/members/", RoomMemberListView.as_view(), name="room-members"),

    # DELETE — remove member (admin only)
    # PATCH — toggle admin   (admin only)
    path("rooms/<uuid:room_id>/members/<int:user_id>/", RoomMemberDetailView.as_view(), name="room-member-detail"),

    # GET — list invites (admin only)
    path("rooms/<uuid:room_id>/invites/", RoomInviteListView.as_view(), name="room-invites"),

    # POST — accept or decline an invite
    path("invites/<uuid:invite_id>/respond/", InviteRespondView.as_view(), name="invite-respond"),

    # POST — mark room as read
    path("rooms/<uuid:room_id>/read/", MarkReadView.as_view(), name="room-mark-read"),

    # GET — message history
    path("rooms/<uuid:room_id>/messages/", MessageListView.as_view(), name="message-list"),
]
