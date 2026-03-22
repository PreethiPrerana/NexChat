# NexChat

Real-time chat application built with **Django**, **Django Channels**, and **WebSockets**.
Supports group rooms and direct messages with JWT-based authentication.

---

## Tech Stack

| Layer | Dev | Prod |
|---|---|---|
| Web server | Daphne (ASGI) | Daphne (ASGI) |
| Database | SQLite | MySQL 8 |
| Channel layer | InMemoryChannelLayer | Redis 7 |
| Auth | JWT (SimpleJWT) | JWT (SimpleJWT) |

---

## Project Structure

```
NexChat/
├── requirements.txt            # root-level (local dev reference)
└── nexchat/                    # Django project root
    ├── manage.py
    ├── requirements.txt        # used by Docker build
    ├── Dockerfile
    ├── docker-compose.yml      # production stack
    ├── .env.example            # copy to .env and fill in values
    ├── logs/                   # created automatically; rotating log files
    ├── nexchat/                # Django settings & routing
    │   ├── settings.py         # dev/prod config via DJANGO_ENV
    │   ├── asgi.py             # ASGI entry-point (HTTP + WebSocket)
    │   ├── urls.py             # root URL conf
    │   └── wsgi.py
    ├── accounts/               # auth app
    │   ├── models.py           # custom User model
    │   ├── views.py            # register, login, me, user-search
    │   ├── serializers.py
    │   └── urls.py
    ├── chat/                   # chat app
    │   ├── models.py           # Room, RoomMember, Message
    │   ├── views.py            # REST API views
    │   ├── consumers.py        # WebSocket consumer
    │   ├── middleware.py       # JWT auth for WebSocket
    │   ├── routing.py          # WebSocket URL patterns
    │   ├── serializers.py
    │   └── urls.py
    ├── static/
    │   └── nexchat.js          # vanilla JS frontend
    └── templates/
        ├── index.html          # chat UI
        └── accounts/
            └── login.html      # login / register
```

---

## Local Development (dev)

### Prerequisites
- Python 3.11+
- (optional) virtualenv

### Setup

```bash
cd nexchat

# create and activate virtualenv
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# install dependencies
pip install -r requirements.txt

# create .env (dev defaults work out of the box)
cp .env.example .env
# DJANGO_ENV=dev is the default — no changes needed for local dev

# run migrations (creates db.sqlite3)
python manage.py migrate

# create a superuser (optional)
python manage.py createsuperuser

# start the ASGI server (handles HTTP + WebSocket)
uvicorn nexchat.asgi:application --host 127.0.0.1 --port 8000 --reload
```

Open [http://localhost:8000](http://localhost:8000) — you'll be redirected to the login page.

> **IMPORTANT — WebSocket requires uvicorn:**
> Django Channels 4.x removed the `runserver` WebSocket override.
> `python manage.py runserver` only handles HTTP — WebSocket connections to `/ws/chat/...` will get a **404**.
> You **must** use `uvicorn` to run the development server.

---

## Production (Docker)

### Prerequisites
- Docker + Docker Compose

### Setup

```bash
cd nexchat

# copy and edit env file
cp .env.example .env
# set DJANGO_ENV=prod, DJANGO_SECRET_KEY, MYSQL_PASSWORD, etc.

# build and start all services
docker compose up --build -d

# create a superuser inside the container
docker compose exec web python manage.py createsuperuser

# view logs
docker compose logs -f web
```

Services started by Docker Compose:

| Service | Image | Port |
|---|---|---|
| `web` | custom (Daphne) | 8000 |
| `db` | mysql:8.0 | 3306 |
| `redis` | redis:7-alpine | — |

---

## REST API

All endpoints (except register and login) require:
```
Authorization: Bearer <access_token>
```

### Authentication

| Method | URL | Description |
|---|---|---|
| POST | `/api/auth/register/` | Create account |
| POST | `/api/auth/login/` | Get access + refresh tokens |
| POST | `/api/auth/refresh/` | Rotate access token |
| GET  | `/api/auth/me/` | Current user profile |
| GET  | `/api/auth/users/?search=<q>` | Search users by username |

### Rooms

| Method | URL | Description |
|---|---|---|
| GET  | `/api/chat/rooms/` | List your rooms |
| POST | `/api/chat/rooms/` | Create group room |
| POST | `/api/chat/rooms/direct/` | Get or create DM |
| GET  | `/api/chat/rooms/<id>/` | Room detail |

### Members

| Method | URL | Description |
|---|---|---|
| GET  | `/api/chat/rooms/<id>/members/` | List members |
| POST | `/api/chat/rooms/<id>/members/` | Add member (group only) |

### Messages

| Method | URL | Description |
|---|---|---|
| GET | `/api/chat/rooms/<id>/messages/` | Message history (paginated) |

Query params for messages: `limit` (max 100), `before` (ISO8601 timestamp).

---

## WebSocket

```
ws://localhost:8000/ws/chat/<room_id>/?token=<access_token>
```

### Frames — Client → Server

```json
{ "type": "message", "content": "Hello!" }
```

### Frames — Server → Client

```json
{ "type": "message", "message_id": "...", "content": "...",
  "sender": { "id": 1, "username": "alice", "display_name": "Alice" },
  "created_at": "2026-03-22T10:00:00Z" }

{ "type": "user_join",  "user": { "id": 1, "username": "alice", "display_name": "Alice" } }
{ "type": "user_leave", "user": { "id": 1, "username": "alice", "display_name": "Alice" } }
{ "type": "error",      "code": "empty_message", "detail": "Message content cannot be empty." }
```

### WebSocket close codes

| Code | Reason |
|---|---|
| 4001 | Invalid or missing JWT token |
| 4003 | User is not a member of the room |
| 4004 | Room not found |

---

## Environment Variables

See [nexchat/.env.example](nexchat/.env.example) for the full list with descriptions.

Key variables:

| Variable | Default | Description |
|---|---|---|
| `DJANGO_ENV` | `dev` | `dev` or `prod` |
| `DJANGO_SECRET_KEY` | *(insecure default)* | Must be changed in prod |
| `DEBUG` | `True` in dev / `False` in prod | Django debug mode |
| `ALLOWED_HOSTS` | `*` in dev | Comma-separated allowed hosts |
| `MYSQL_*` | — | MySQL credentials (prod only) |
| `REDIS_HOST` | `redis` | Redis hostname (prod only) |
| `MESSAGE_PAGE_SIZE` | `50` | Messages per page |

---

## Dev vs Prod Configuration Summary

| Setting | Dev | Prod |
|---|---|---|
| Database | SQLite | MySQL 8 |
| Channel layer | InMemoryChannelLayer | Redis |
| `DEBUG` | `True` | `False` |
| Security headers | off | HSTS, XSS, CSP, HTTPS redirect |
| Cookie flags | off | `Secure`, `HttpOnly` |
| Email | Console backend | SMTP |
| CORS | unrestricted | `CORS_ALLOWED_ORIGINS` list |
| Log level | DEBUG | WARNING |
| Log output | file + console | file + console |

---

## Logs

Log files are written to `nexchat/logs/` (created automatically):

| File | Content |
|---|---|
| `logs/django.log` | Django + accounts events |
| `logs/chat.log` | WebSocket + chat events |

Files rotate at 10 MB, keeping 5 backups.
