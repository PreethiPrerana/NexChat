# NexChat — API Reference

All REST endpoints are prefixed with `/api/`.  
All endpoints except registration and login require a JWT access token:

```
Authorization: Bearer <access_token>
```

---

## Auth

### Register
```
POST /api/auth/register/
```
**Body**
```json
{
  "username":     "alice",
  "email":        "alice@example.com",
  "display_name": "Alice",          // optional
  "password":     "strongpass123",
  "password2":    "strongpass123"
}
```
**Response** `201 Created`
```json
{ "id": 1, "username": "alice", "email": "alice@example.com", "display_name": "Alice" }
```

---

### Login
```
POST /api/auth/login/
```
**Body**
```json
{ "username": "alice", "password": "strongpass123" }
```
**Response** `200 OK`
```json
{ "access": "<jwt_access_token>", "refresh": "<jwt_refresh_token>" }
```

---

### Refresh token
```
POST /api/auth/refresh/
```
**Body**
```json
{ "refresh": "<jwt_refresh_token>" }
```
**Response** `200 OK`
```json
{ "access": "<new_access_token>", "refresh": "<rotated_refresh_token>" }
```

---

### Current user
```
GET /api/auth/me/
```
**Response** `200 OK`
```json
{ "id": 1, "username": "alice", "email": "alice@example.com", "display_name": "Alice" }
```

---

## Rooms

### List my rooms
```
GET /api/chat/rooms/
```
Returns all rooms the authenticated user is a member of.

**Response** `200 OK`
```json
[
  {
    "id":           "550e8400-...",
    "name":         "Engineering",
    "room_type":    "group",
    "created_by":   { "id": 1, "username": "alice", ... },
    "member_count": 4,
    "created_at":   "2024-01-01T12:00:00Z"
  }
]
```

---

### Create group room
```
POST /api/chat/rooms/
```
**Body**
```json
{
  "name":       "Engineering",
  "member_ids": [2, 3, 4]
}
```
`member_ids` — list of user IDs to add (creator is always included).

**Response** `201 Created` — room object (see above)

---

### Get or create direct message room
```
POST /api/chat/rooms/direct/
```
**Body**
```json
{ "user_id": 2 }
```
Idempotent — always returns the same room for the user pair.

**Response** `200 OK` — room object

---

### Room detail
```
GET /api/chat/rooms/<room_id>/
```
**Response** `200 OK` — room object  
**Errors** `403` if not a member, `404` if not found

---

## Members

### List room members
```
GET /api/chat/rooms/<room_id>/members/
```
**Response** `200 OK`
```json
[
  {
    "user":      { "id": 1, "username": "alice", "display_name": "Alice" },
    "joined_at": "2024-01-01T12:00:00Z"
  }
]
```

---

### Add member (group rooms only)
```
POST /api/chat/rooms/<room_id>/members/
```
**Body**
```json
{ "user_id": 5 }
```
**Response** `201 Created` or `200 OK` if already a member

---

## Messages

### Message history
```
GET /api/chat/rooms/<room_id>/messages/
```
Returns up to `limit` messages, oldest-first within the page.

**Query params**

| Param    | Type      | Default | Description                                    |
|----------|-----------|---------|------------------------------------------------|
| `limit`  | int       | 50      | Max messages to return (capped at 100)         |
| `before` | ISO8601   | —       | Return messages created before this timestamp  |

**Response** `200 OK`
```json
[
  {
    "id":         "660e8400-...",
    "room":       "550e8400-...",
    "sender":     { "id": 1, "username": "alice", "display_name": "Alice" },
    "content":    "Hey everyone!",
    "created_at": "2024-01-01T12:01:00Z"
  }
]
```

---

## WebSocket

### Connect
```
ws://host/ws/chat/<room_id>/?token=<access_token>
```

The JWT access token is passed as a **query parameter**.  
The server validates it on the handshake. Invalid / expired tokens are rejected with close code `4001`.

**Close codes**

| Code | Reason                         |
|------|--------------------------------|
| 4001 | Unauthenticated / token invalid |
| 4003 | Not a member of the room       |
| 4004 | Room not found                 |

---

### Client → Server frames

#### Send a message
```json
{ "type": "message", "content": "Hello, world!" }
```

---

### Server → Client frames

#### New message
Broadcast to all connected members when a message is saved.
```json
{
  "type":       "message",
  "message_id": "660e8400-...",
  "content":    "Hello, world!",
  "sender": {
    "id":           1,
    "username":     "alice",
    "display_name": "Alice"
  },
  "created_at": "2024-01-01T12:01:00Z"
}
```

#### User joined
```json
{ "type": "user_join", "user": { "id": 2, "username": "bob", "display_name": "Bob" } }
```

#### User left
```json
{ "type": "user_leave", "user": { "id": 2, "username": "bob", "display_name": "Bob" } }
```

#### Error
```json
{ "type": "error", "code": "empty_message", "detail": "Message content cannot be empty." }
```

**Error codes**

| Code            | Meaning                          |
|-----------------|----------------------------------|
| `invalid_json`  | Frame was not valid JSON         |
| `unknown_type`  | Unrecognised frame type          |
| `empty_message` | Message content was blank        |
| `too_long`      | Content exceeded 4000 characters |