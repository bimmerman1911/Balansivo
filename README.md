# Balansivo

Balansivo is a mobile-friendly Flask web app for tracking personal balances using UUID-only access.

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
- **Flask**
- **SQLite**

## Files

- `uuid_balance_app.py` — the full application
- `uuid_balance_app.db` — SQLite database, created automatically on first run

## Installation

Install Flask:

```bash
pip install flask
```

## Running the app

Start the server:

```bash
python uuid_balance_app.py
```

By default, the app runs on:

```text
http://127.0.0.1:8000
```

Then open that address in your browser.

## How it works

### 1. Create a user
On the home page, create a new user. Balansivo generates:

- a **private UUID** for the owner
- a **public UUID** for guests

### 2. Owner access
Using the private UUID, the owner can:

- open the private dashboard
- add people by first and last name
- add or subtract amounts from balances
- upload a Swish QR image

### 3. Guest access
Using the public UUID, guests can:

- see the list of people as **initials only**
- open their person page
- view the balance
- add or subtract an amount

### 4. Direct UUID access
If someone visits:

```text
/UUID
```

Balansivo checks whether the UUID is private or public and sends the visitor to the correct page automatically.

## Balance logic

- **Positive balance**: the person owes the owner money
- **Negative balance**: the owner owes the person money

## Image upload

The owner can upload an image intended to be a **Swish QR code**.

- Supported formats: PNG, JPG, WEBP, GIF
- Max size: 4 MB
- Displayed on all public person pages under the title **Swish**

## Database persistence

Balansivo uses SQLite for storage.

The database file is stored next to the Python script as:

```text
uuid_balance_app.db
```

Because the database is stored on disk, data remains available after the script is stopped and started again.

## Security note

Balansivo uses **UUID-only access** and no passwords.

That means:

- the **private UUID** grants full owner access
- the **public UUID** grants guest access

Treat the private UUID like a secret link. Anyone who gets it can control the private dashboard.

## Optional environment variables

You can change the host or port with environment variables:

```bash
APP_HOST=0.0.0.0 APP_PORT=8000 python uuid_balance_app.py
```

You can also enable Flask debug mode:

```bash
APP_DEBUG=1 python uuid_balance_app.py
```

## License

Use and modify freely for your own project.
