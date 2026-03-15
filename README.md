# Balansivo

Balansivo is a mobile-friendly FastAPI web app for tracking personal balances using UUID-only access.

Instead of usernames and passwords, each account gets two UUIDs:

- **Private UUID** — opens the owner dashboard
- **Public UUID** — opens the guest-facing profile

The owner can add people, manage balances, and upload a **Swish** QR code image. Visitors using the public UUID can only see people by **initials**, open their entry, view the balance, and adjust it.

## Features

- Modern mobile-adapted interface
- UUID-only login flow
- Automatic routing from `/UUID` to the correct page type
- Create new users with:
  - one **private UUID**
  - one **public UUID**
- Private dashboard:
  - add people by first and last name
  - increase or decrease balances
  - upload a Swish QR code image
- Public profile:
  - shows only initials for privacy
  - lets visitors open a person page
  - shows the uploaded Swish QR code on each public person page
- Persistent SQLite database retained on disk between restarts

## Tech stack

- **Python**
- **FastAPI** (application framework)
- **Uvicorn** (separate ASGI web server)
- **SQLite**

## Files

- `balansivo.py` — the full application
- `uuid_balance_app.db` — SQLite database, created automatically on first run

## Installation

Install dependencies:

```bash
pip install fastapi uvicorn jinja2 python-multipart
```

## Running the app

### Option 1: run with Python (starts Uvicorn)

```bash
python balansivo.py
```

### Option 2: run Uvicorn directly

```bash
uvicorn balansivo:app --host 0.0.0.0 --port 8000
```

By default, the app runs on:

```text
http://127.0.0.1:8000
```

## Database persistence

Balansivo uses SQLite for storage.

The database file is stored in the current working directory by default as:

```text
uuid_balance_app.db
```

This makes it easy to drop `balansivo.py` into any webserver folder and run it there.

You can also choose a specific data folder with:

```bash
BALANSIVO_DATA_DIR=/path/to/data python balansivo.py
```

Because the database is stored on disk, data remains available after the script is stopped and started again.

## Security note

Balansivo uses **UUID-only access** and no passwords.

That means:

- the **private UUID** grants full owner access
- the **public UUID** grants guest access

Treat the private UUID like a secret link. Anyone who gets it can control the private dashboard.

## Optional environment variables

You can change runtime behavior with environment variables:

```bash
APP_HOST=0.0.0.0 APP_PORT=8000 APP_ROOT_PATH=/myapp BALANSIVO_DATA_DIR=/path/to/data python balansivo.py
```

- `APP_HOST` and `APP_PORT` control bind address and port
- `APP_ROOT_PATH` lets the app work behind a reverse proxy subpath (for example `/myapp`)
- `BALANSIVO_DATA_DIR` controls where the SQLite file is stored

## License

Use and modify freely for your own project.
