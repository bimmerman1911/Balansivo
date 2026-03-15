#!/usr/bin/env python3
import base64
import os
import sqlite3
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps

try:
    from flask import Flask, abort, redirect, render_template_string, request, url_for
except ModuleNotFoundError as exc:
    raise SystemExit(
        "This app requires Flask. Install it with: pip install flask"
    ) from exc

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "uuid_balance_app.db")
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_uuid TEXT UNIQUE NOT NULL,
                private_uuid TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                qr_image BLOB,
                qr_mime TEXT
            );

            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                balance_cents INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_users_public_uuid ON users(public_uuid);
            CREATE INDEX IF NOT EXISTS idx_users_private_uuid ON users(private_uuid);
            CREATE INDEX IF NOT EXISTS idx_people_user_id ON people(user_id);
            """
        )


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def format_currency(cents: int) -> str:
    value = Decimal(cents) / Decimal("100")
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,.2f}"


def parse_amount_to_cents(raw: str) -> int:
    cleaned = (raw or "").strip().replace(",", ".")
    if not cleaned:
        raise ValueError("Amount is required.")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Amount must be numeric.") from exc
    cents = int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cents == 0:
        raise ValueError("Amount must be greater than 0.")
    if abs(cents) > 100_000_000:
        raise ValueError("Amount is too large.")
    return abs(cents)


def initials(first_name: str, last_name: str) -> str:
    first = (first_name or "").strip()[:1].upper()
    last = (last_name or "").strip()[:1].upper()
    return (first + last) or "?"


def qr_data_uri(user_row) -> str | None:
    if not user_row["qr_image"] or not user_row["qr_mime"]:
        return None
    encoded = base64.b64encode(user_row["qr_image"]).decode("ascii")
    return f"data:{user_row['qr_mime']};base64,{encoded}"


def get_user_by_private_uuid(private_uuid: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE private_uuid = ?",
            (private_uuid,),
        ).fetchone()


def get_user_by_public_uuid(public_uuid: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE public_uuid = ?",
            (public_uuid,),
        ).fetchone()


def get_user_by_any_uuid(token: str):
    with get_conn() as conn:
        user = conn.execute(
            "SELECT *, 'private' AS token_type FROM users WHERE private_uuid = ?",
            (token,),
        ).fetchone()
        if user:
            return user
        return conn.execute(
            "SELECT *, 'public' AS token_type FROM users WHERE public_uuid = ?",
            (token,),
        ).fetchone()


def get_people_for_user(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT id, first_name, last_name, balance_cents, created_at
            FROM people
            WHERE user_id = ?
            ORDER BY lower(first_name), lower(last_name), id
            """,
            (user_id,),
        ).fetchall()


def get_person_for_private(private_uuid: str, person_id: int):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT p.*, u.private_uuid, u.public_uuid, u.qr_image, u.qr_mime
            FROM people p
            JOIN users u ON p.user_id = u.id
            WHERE u.private_uuid = ? AND p.id = ?
            """,
            (private_uuid, person_id),
        ).fetchone()


def get_person_for_public(public_uuid: str, person_id: int):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT p.*, u.private_uuid, u.public_uuid, u.qr_image, u.qr_mime
            FROM people p
            JOIN users u ON p.user_id = u.id
            WHERE u.public_uuid = ? AND p.id = ?
            """,
            (public_uuid, person_id),
        ).fetchone()


def require_private_user(view_func):
    @wraps(view_func)
    def wrapper(private_uuid, *args, **kwargs):
        user = get_user_by_private_uuid(private_uuid)
        if not user:
            abort(404)
        return view_func(user, *args, **kwargs)
    return wrapper


def require_public_user(view_func):
    @wraps(view_func)
    def wrapper(public_uuid, *args, **kwargs):
        user = get_user_by_public_uuid(public_uuid)
        if not user:
            abort(404)
        return view_func(user, *args, **kwargs)
    return wrapper


BASE_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>
  <style>
    :root {
      --bg: #07111f;
      --bg-2: #0b1728;
      --card: rgba(255,255,255,0.08);
      --card-border: rgba(255,255,255,0.12);
      --text: #eff6ff;
      --muted: #9eb2ca;
      --accent: #6ee7f9;
      --accent-2: #8b5cf6;
      --good: #34d399;
      --bad: #f87171;
      --warn: #fbbf24;
      --shadow: 0 24px 60px rgba(0,0,0,0.35);
      --radius: 24px;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--text); background:
      radial-gradient(circle at top left, rgba(110,231,249,0.12), transparent 28%),
      radial-gradient(circle at top right, rgba(139,92,246,0.18), transparent 30%),
      linear-gradient(180deg, var(--bg), var(--bg-2));
    }
    a { color: inherit; text-decoration: none; }
    .page {
      width: min(1100px, calc(100vw - 24px));
      margin: 0 auto;
      padding: 18px 0 42px;
    }
    .site-header {
      margin-bottom: 16px;
    }
    .site-brand {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      width: fit-content;
      padding: 8px 10px;
      border-radius: 16px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
    }
    .site-brand .brand-icon {
      width: 38px;
      height: 38px;
      border-radius: 12px;
    }
    .site-brand .brand-icon::after {
      font-size: 1.5rem;
    }
    .site-brand .brand-title {
      font-size: 1.2rem;
      line-height: 1;
    }
    .site-brand .brand-mark {
      width: 96px;
      height: 4px;
    }
    .hero {
      display: grid;
      gap: 18px;
      padding: 18px 0 8px;
    }
    .brand {
      display: inline-flex;
      align-items: center;
      gap: 14px;
      width: fit-content;
    }
    .brand-icon {
      width: 62px;
      height: 62px;
      border-radius: 18px;
      position: relative;
      background: linear-gradient(150deg, #173158, #091325);
      border: 1px solid rgba(114, 179, 255, 0.35);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.15),
        0 12px 24px rgba(0,0,0,0.4);
      overflow: hidden;
    }
    .brand-icon::before {
      content: "";
      position: absolute;
      width: 72%;
      height: 20%;
      top: 0;
      left: 0;
      border-bottom-right-radius: 20px;
      background: linear-gradient(90deg, rgba(180, 225, 255, 0.45), rgba(180,225,255,0.12));
    }
    .brand-icon::after {
      content: "B";
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      font-size: 2.7rem;
      font-weight: 900;
      color: #75c6ff;
      text-shadow: 0 0 12px rgba(117,198,255,0.25);
    }
    .brand-name {
      display: grid;
      gap: 6px;
    }
    .brand-title {
      margin: 0;
      font-size: clamp(1.8rem, 4.3vw, 3rem);
      letter-spacing: -0.04em;
      font-weight: 800;
      line-height: 0.95;
    }
    .brand-mark {
      width: min(240px, 52vw);
      height: 6px;
      border-radius: 999px;
      background: linear-gradient(90deg, #69c2ff 0%, #69c2ff 88%, transparent 88%);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      width: fit-content;
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 999px;
      padding: 8px 14px;
      background: rgba(255,255,255,0.05);
      color: var(--muted);
      font-size: 0.9rem;
      backdrop-filter: blur(16px);
    }
    h1 {
      margin: 0;
      font-size: clamp(2rem, 5vw, 4rem);
      line-height: 1.04;
      letter-spacing: -0.04em;
    }
    .sub {
      color: var(--muted);
      font-size: 1.02rem;
      max-width: 760px;
      line-height: 1.65;
      margin: 0;
    }
    .grid {
      display: grid;
      gap: 18px;
    }
    .grid-2 {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .grid-3 {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .card {
      background: var(--card);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 20px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(20px);
    }
    .card h2, .card h3, .card h4 {
      margin-top: 0;
      margin-bottom: 10px;
      letter-spacing: -0.03em;
    }
    .muted { color: var(--muted); }
    .stack { display: grid; gap: 12px; }
    .stack-lg { display: grid; gap: 18px; }
    .row {
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }
    .split {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      flex-wrap: wrap;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 44px;
      height: 44px;
      border-radius: 16px;
      padding: 0 14px;
      font-weight: 700;
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.1);
    }
    .pill.good { color: var(--good); }
    .pill.bad { color: var(--bad); }
    .pill.warn { color: var(--warn); }
    label {
      display: grid;
      gap: 8px;
      font-size: 0.95rem;
      color: var(--muted);
    }
    input, button, .button, select {
      width: 100%;
      border: 0;
      border-radius: 18px;
      padding: 14px 16px;
      font-size: 1rem;
      font-family: inherit;
    }
    input, select {
      color: var(--text);
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.1);
      outline: none;
      transition: border-color .18s ease, transform .18s ease, background .18s ease;
    }
    input:focus, select:focus {
      border-color: rgba(110,231,249,0.8);
      background: rgba(255,255,255,0.08);
      transform: translateY(-1px);
    }
    button, .button {
      cursor: pointer;
      font-weight: 700;
      color: #04111d;
      background: linear-gradient(135deg, var(--accent), #d8fbff);
      transition: transform .18s ease, box-shadow .18s ease, opacity .18s ease;
      box-shadow: 0 12px 30px rgba(110,231,249,0.24);
      text-align: center;
      display: inline-flex;
      justify-content: center;
      align-items: center;
      gap: 10px;
    }
    button.secondary, .button.secondary {
      color: var(--text);
      background: rgba(255,255,255,0.08);
      box-shadow: none;
      border: 1px solid rgba(255,255,255,0.1);
    }
    button.ghost, .button.ghost {
      color: var(--muted);
      background: transparent;
      box-shadow: none;
      border: 1px dashed rgba(255,255,255,0.18);
    }
    button:hover, .button:hover { transform: translateY(-1px); }
    .actions { display: flex; gap: 10px; flex-wrap: wrap; }
    .actions > * { flex: 1 1 180px; }
    .message {
      border-radius: 18px;
      padding: 14px 16px;
      font-size: 0.96rem;
      border: 1px solid rgba(255,255,255,0.1);
    }
    .message.ok { background: rgba(52, 211, 153, 0.12); color: #c8ffed; border-color: rgba(52, 211, 153, 0.24); }
    .message.err { background: rgba(248, 113, 113, 0.12); color: #ffd3d3; border-color: rgba(248, 113, 113, 0.24); }
    .message.info { background: rgba(110,231,249,0.1); color: #d6fbff; border-color: rgba(110,231,249,0.22); }
    .person-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 14px;
    }
    .person-card {
      display: grid;
      gap: 14px;
      padding: 16px;
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 22px;
      min-height: 180px;
    }
    .person-link {
      display: grid;
      gap: 14px;
      height: 100%;
    }
    .avatar {
      width: 58px;
      height: 58px;
      border-radius: 18px;
      display: grid;
      place-items: center;
      font-weight: 800;
      letter-spacing: 0.06em;
      background:
        linear-gradient(135deg, rgba(110,231,249,0.16), rgba(139,92,246,0.18)),
        rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.1);
    }
    .metric {
      font-size: clamp(1.55rem, 4vw, 2.15rem);
      font-weight: 800;
      letter-spacing: -0.05em;
    }
    .metric.positive { color: #d8fff0; }
    .metric.negative { color: #ffd7d7; }
    .metric.zero { color: #fff7cc; }
    .tiny { font-size: 0.84rem; color: var(--muted); }
    .uuid {
      word-break: break-all;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.92rem;
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.08);
    }
    .qr-box {
      width: min(100%, 260px);
      aspect-ratio: 1 / 1;
      border-radius: 24px;
      background: rgba(255,255,255,0.06);
      border: 1px dashed rgba(255,255,255,0.18);
      display: grid;
      place-items: center;
      overflow: hidden;
    }
    .qr-box img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      background: white;
    }
    .tabs {
      display: inline-flex;
      gap: 10px;
      padding: 6px;
      border-radius: 20px;
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.1);
      width: fit-content;
    }
    .tab-btn {
      width: auto;
      min-width: 130px;
    }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }
    .helper-list {
      display: grid;
      gap: 8px;
      margin: 0;
      padding-left: 20px;
      color: var(--muted);
      line-height: 1.6;
    }
    @media (max-width: 860px) {
      .grid-2, .grid-3 { grid-template-columns: 1fr; }
      .page { width: min(760px, calc(100vw - 18px)); }
    }
    @media (max-width: 520px) {
      .card { padding: 16px; border-radius: 22px; }
      .page { width: calc(100vw - 14px); }
      .actions > * { flex-basis: 100%; }
      .tab-btn { min-width: 112px; }
      input, button, .button { border-radius: 16px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <header class="site-header">
      <a class="site-brand" href="/" aria-label="Balansivo home">
        <div class="brand-icon"></div>
        <div class="brand-name">
          <p class="brand-title">Balansivo</p>
          <div class="brand-mark"></div>
        </div>
      </a>
    </header>
    {{ body|safe }}
  </div>
  <script>
    function showTab(id) {
      document.querySelectorAll(".tab-panel").forEach((el) => el.classList.remove("active"));
      document.querySelectorAll("[data-tab-button]").forEach((el) => el.classList.remove("secondary"));
      const panel = document.getElementById(id);
      if (panel) panel.classList.add("active");
      const btn = document.querySelector(`[data-tab-button="${id}"]`);
      if (btn) btn.classList.add("secondary");
    }

    async function copyText(value) {
      try {
        await navigator.clipboard.writeText(value);
        alert("Copied");
      } catch (err) {
        alert(value);
      }
    }
  </script>
</body>
</html>
"""


def render_page(title: str, body: str):
    return render_template_string(BASE_HTML, title=title, body=body)


@app.errorhandler(404)
def not_found(_):
    body = """
    <section class="hero">
      <span class="badge">Not found</span>
      <h1>That UUID does not exist.</h1>
      <p class="sub">Check the token and try again. Public and private UUIDs are both supported directly through the URL.</p>
    </section>
    <div class="actions">
      <a class="button" href="/">Back to start</a>
    </div>
    """
    return render_page("Not found", body), 404


@app.errorhandler(413)
def too_large(_):
    body = """
    <section class="hero">
      <span class="badge">Upload too large</span>
      <h1>The image is too big.</h1>
      <p class="sub">Use a PNG, JPG, WEBP or GIF under 4 MB for the Swish QR code image.</p>
    </section>
    <div class="actions">
      <a class="button" href="/">Back to start</a>
    </div>
    """
    return render_page("Upload too large", body), 413


@app.get("/")
def home():
    body = """
    <section class="hero">
      <h1>Track balances with UUID-only access.</h1>
      <p class="sub">Create an account, receive one private UUID and one public UUID, then manage people and balances with no password at all. Anyone with the public UUID can open your profile and adjust their own balance. A Swish QR image can be shown on every public person page.</p>
    </section>

    <div class="tabs">
      <button class="tab-btn secondary" data-tab-button="open-tab" onclick="showTab('open-tab')">Open with UUID</button>
      <button class="tab-btn" data-tab-button="create-tab" onclick="showTab('create-tab')">Create user</button>
    </div>

    <div id="open-tab" class="tab-panel active">
      <div class="grid grid-2" style="margin-top:18px;">
        <div class="card stack-lg">
          <div>
            <h2>Open a page</h2>
            <p class="muted">Paste either a private UUID or a public UUID. The app will detect the correct page type automatically.</p>
          </div>
          <form class="stack" method="post" action="/open">
            <label>
              UUID
              <input name="uuid" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" autocomplete="off" required>
            </label>
            <button type="submit">Open page</button>
          </form>
        </div>

        <div class="card stack-lg">
          <div>
            <h2>How it works</h2>
            <ul class="helper-list">
              <li>Private UUID opens the owner dashboard.</li>
              <li>Public UUID opens the guest-facing profile.</li>
              <li>Owners see full names. Guests only see initials.</li>
              <li>Balances can be increased or decreased from both sides.</li>
            </ul>
          </div>
        </div>
      </div>
    </div>

    <div id="create-tab" class="tab-panel">
      <div class="grid grid-2" style="margin-top:18px;">
        <div class="card stack-lg">
          <div>
            <h2>Create a new user</h2>
            <p class="muted">This generates one public UUID and one private UUID. There is no password. The private UUID is the full control key, so keep it secret.</p>
          </div>
          <form method="post" action="/create-user">
            <button type="submit">Generate UUID pair</button>
          </form>
        </div>
        <div class="card stack-lg">
          <div>
            <h2>Security note</h2>
            <p class="muted">This matches your requested design, but a UUID-only system should be treated like a magic link. Anyone who gets the private UUID gets full access.</p>
          </div>
        </div>
      </div>
    </div>
    """
    return render_page("Balansivo", body)


@app.post("/open")
def open_uuid():
    token = (request.form.get("uuid") or "").strip()
    if not token:
        return redirect(url_for("home"))
    return redirect(f"/{token}")


@app.post("/create-user")
def create_user():
    public_uuid = str(uuid.uuid4())
    private_uuid = str(uuid.uuid4())

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (public_uuid, private_uuid, created_at) VALUES (?, ?, ?)",
            (public_uuid, private_uuid, now_iso()),
        )

    private_link = request.host_url.rstrip("/") + f"/{private_uuid}"
    public_link = request.host_url.rstrip("/") + f"/{public_uuid}"

    body = """
    <section class="hero">
      <span class="badge">User created</span>
      <h1>Your UUID pair is ready.</h1>
      <p class="sub">Store the private UUID safely. Anyone with it can access the private dashboard. The public UUID is for guest access to your profile.</p>
    </section>

    <div class="grid grid-2">
      <div class="card stack">
        <h2>Private UUID</h2>
        <div class="uuid">{{ private_uuid }}</div>
        <div class="tiny">Use this for your owner dashboard.</div>
        <div class="actions">
          <button type="button" onclick="copyText('{{ private_uuid }}')">Copy UUID</button>
          <button type="button" class="secondary" onclick="copyText('{{ private_link }}')">Copy private link</button>
        </div>
      </div>

      <div class="card stack">
        <h2>Public UUID</h2>
        <div class="uuid">{{ public_uuid }}</div>
        <div class="tiny">Share this with anyone who should access the public balance page.</div>
        <div class="actions">
          <button type="button" onclick="copyText('{{ public_uuid }}')">Copy UUID</button>
          <button type="button" class="secondary" onclick="copyText('{{ public_link }}')">Copy public link</button>
        </div>
      </div>
    </div>

    <div class="card stack-lg" style="margin-top:18px;">
      <h2>Next steps</h2>
      <div class="actions">
        <a class="button" href="/{{ private_uuid }}">Open private dashboard</a>
        <a class="button secondary" href="/{{ public_uuid }}">Open public page</a>
        <a class="button ghost" href="/">Back to start</a>
      </div>
    </div>
    """
    return render_template_string(BASE_HTML, title="User created", body=render_template_string(
        body,
        private_uuid=private_uuid,
        public_uuid=public_uuid,
        private_link=private_link,
        public_link=public_link,
    ))


@app.get("/<token>")
def route_by_uuid(token):
    user = get_user_by_any_uuid(token)
    if not user:
        abort(404)
    if user["token_type"] == "private":
        return redirect(url_for("private_dashboard", private_uuid=token))
    return redirect(url_for("public_profile", public_uuid=token))


@app.get("/private/<private_uuid>")
@require_private_user
def private_dashboard(user):
    people = get_people_for_user(user["id"])
    public_link = request.host_url.rstrip("/") + f"/{user['public_uuid']}"
    private_link = request.host_url.rstrip("/") + f"/{user['private_uuid']}"
    qr_uri = qr_data_uri(user)

    body = render_template_string(
        """
        <section class="hero">
          <span class="badge">Private dashboard</span>
          <h1>Manage people, balances, and your Swish QR.</h1>
          <p class="sub">Add people by first and last name, adjust balances, and manage the QR image that shows up on every public person page.</p>
        </section>

        <div class="grid grid-3">
          <div class="card stack">
            <h3>Private UUID</h3>
            <div class="uuid">{{ user.private_uuid }}</div>
            <div class="actions">
              <button type="button" onclick="copyText('{{ user.private_uuid }}')">Copy UUID</button>
              <button type="button" class="secondary" onclick="copyText('{{ private_link }}')">Copy link</button>
            </div>
          </div>
          <div class="card stack">
            <h3>Public UUID</h3>
            <div class="uuid">{{ user.public_uuid }}</div>
            <div class="actions">
              <button type="button" onclick="copyText('{{ user.public_uuid }}')">Copy UUID</button>
              <button type="button" class="secondary" onclick="copyText('{{ public_link }}')">Copy link</button>
            </div>
          </div>
          <div class="card stack">
            <h3>People</h3>
            <div class="metric">{{ people|length }}</div>
            <div class="muted">Tracked people</div>
            <a class="button secondary" href="/{{ user.public_uuid }}">Open public view</a>
          </div>
        </div>

        <div class="grid grid-2" style="margin-top:18px;">
          <div class="card stack-lg">
            <div>
              <h2>Add a person</h2>
              <p class="muted">Each person starts at 0.00. Positive means they owe you. Negative means you owe them.</p>
            </div>
            <form class="stack" method="post" action="/private/{{ user.private_uuid }}/people">
              <label>
                First name
                <input name="first_name" placeholder="Anna" required>
              </label>
              <label>
                Last name
                <input name="last_name" placeholder="Andersson" required>
              </label>
              <button type="submit">Add person</button>
            </form>
          </div>

          <div class="card stack-lg">
            <div class="split">
              <div>
                <h2>Swish QR image</h2>
                <p class="muted">Upload a square-friendly QR code image. It will appear with the title <strong>Swish</strong> on every public person page.</p>
              </div>
              <div class="qr-box">
                {% if qr_uri %}
                  <img src="{{ qr_uri }}" alt="Swish QR code">
                {% else %}
                  <div class="muted">No QR uploaded yet</div>
                {% endif %}
              </div>
            </div>
            <form class="stack" method="post" enctype="multipart/form-data" action="/private/{{ user.private_uuid }}/upload-swish">
              <label>
                QR image
                <input type="file" name="qr_image" accept="image/png,image/jpeg,image/webp,image/gif" required>
              </label>
              <button type="submit">Upload / replace Swish QR</button>
            </form>
          </div>
        </div>

        <div class="card stack-lg" style="margin-top:18px;">
          <div class="split">
            <div>
              <h2>People and balances</h2>
              <p class="muted">Adjust directly from your private dashboard.</p>
            </div>
            <a class="button ghost" href="/">Back to start</a>
          </div>

          {% if people %}
            <div class="person-grid">
              {% for person in people %}
                <div class="person-card">
                  <div class="split">
                    <div class="row">
                      <div class="avatar">{{ initials(person['first_name'], person['last_name']) }}</div>
                      <div>
                        <div><strong>{{ person['first_name'] }} {{ person['last_name'] }}</strong></div>
                        <div class="tiny">ID {{ person['id'] }}</div>
                      </div>
                    </div>
                    <div class="pill {% if person['balance_cents'] > 0 %}good{% elif person['balance_cents'] < 0 %}bad{% else %}warn{% endif %}">
                      {{ format_currency(person['balance_cents']) }}
                    </div>
                  </div>

                  <div class="metric {% if person['balance_cents'] > 0 %}positive{% elif person['balance_cents'] < 0 %}negative{% else %}zero{% endif %}">
                    {{ format_currency(person['balance_cents']) }}
                  </div>
                  <div class="tiny">Positive means they owe you more.</div>

                  <form class="stack" method="post" action="/private/{{ user.private_uuid }}/people/{{ person['id'] }}/adjust">
                    <label>
                      Amount
                      <input name="amount" inputmode="decimal" placeholder="100" required>
                    </label>
                    <div class="actions">
                      <button type="submit" name="action" value="add">Add amount</button>
                      <button type="submit" name="action" value="subtract" class="secondary">Subtract amount</button>
                    </div>
                  </form>
                </div>
              {% endfor %}
            </div>
          {% else %}
            <div class="message info">No people added yet. Add your first person above.</div>
          {% endif %}
        </div>
        """,
        user=user,
        people=people,
        format_currency=format_currency,
        initials=initials,
        qr_uri=qr_uri,
        public_link=public_link,
        private_link=private_link,
    )
    return render_page("Private dashboard", body)


@app.post("/private/<private_uuid>/people")
@require_private_user
def add_person(user):
    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()

    if not first_name or not last_name:
        return render_message_page(
            "Missing name",
            "Both first name and last name are required.",
            f"/private/{user['private_uuid']}",
            is_error=True,
        )

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO people (user_id, first_name, last_name, balance_cents, created_at)
            VALUES (?, ?, ?, 0, ?)
            """,
            (user["id"], first_name, last_name, now_iso()),
        )

    return redirect(url_for("private_dashboard", private_uuid=user["private_uuid"]))


@app.post("/private/<private_uuid>/people/<int:person_id>/adjust")
@require_private_user
def adjust_person_private(user, person_id):
    person = get_person_for_private(user["private_uuid"], person_id)
    if not person:
        abort(404)

    action = (request.form.get("action") or "").strip().lower()
    try:
        amount_cents = parse_amount_to_cents(request.form.get("amount"))
    except ValueError as exc:
        return render_message_page(
            "Invalid amount",
            str(exc),
            f"/private/{user['private_uuid']}",
            is_error=True,
        )

    delta = amount_cents if action == "add" else -amount_cents
    with get_conn() as conn:
        conn.execute(
            "UPDATE people SET balance_cents = balance_cents + ? WHERE id = ?",
            (delta, person_id),
        )

    return redirect(url_for("private_dashboard", private_uuid=user["private_uuid"]))


@app.post("/private/<private_uuid>/upload-swish")
@require_private_user
def upload_swish(user):
    file = request.files.get("qr_image")
    if not file or not file.filename:
        return render_message_page(
            "No image selected",
            "Choose an image file before uploading.",
            f"/private/{user['private_uuid']}",
            is_error=True,
        )

    mime = (file.mimetype or "").lower()
    if mime not in ALLOWED_MIME:
        return render_message_page(
            "Unsupported image",
            "Use PNG, JPG, WEBP or GIF.",
            f"/private/{user['private_uuid']}",
            is_error=True,
        )

    payload = file.read()
    if not payload:
        return render_message_page(
            "Empty image",
            "The uploaded file was empty.",
            f"/private/{user['private_uuid']}",
            is_error=True,
        )

    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET qr_image = ?, qr_mime = ? WHERE id = ?",
            (payload, mime, user["id"]),
        )

    return redirect(url_for("private_dashboard", private_uuid=user["private_uuid"]))


@app.get("/public/<public_uuid>")
@require_public_user
def public_profile(user):
    people = get_people_for_user(user["id"])

    body = render_template_string(
        """
        <section class="hero">
          <span class="badge">Public page</span>
          <h1>Choose your initials.</h1>
          <p class="sub">Only initials are shown here. Open your entry to view the balance and adjust it.</p>
        </section>

        <div class="card stack-lg">
          <div class="split">
            <div>
              <h2>People</h2>
              <p class="muted">Guest-facing view for public UUID access.</p>
            </div>
            <a class="button ghost" href="/">Back to start</a>
          </div>

          {% if people %}
            <div class="person-grid">
              {% for person in people %}
                <a class="person-card person-link" href="/public/{{ user.public_uuid }}/people/{{ person['id'] }}">
                  <div class="avatar">{{ initials(person['first_name'], person['last_name']) }}</div>
                  <div>
                    <div class="metric zero">
                      {{ initials(person['first_name'], person['last_name']) }}
                    </div>
                    <div class="tiny">Tap to open this balance page</div>
                  </div>
                </a>
              {% endfor %}
            </div>
          {% else %}
            <div class="message info">There are no people on this profile yet.</div>
          {% endif %}
        </div>
        """,
        user=user,
        people=people,
        initials=initials,
        format_currency=format_currency,
    )
    return render_page("Public profile", body)


@app.get("/public/<public_uuid>/people/<int:person_id>")
@require_public_user
def public_person(user, person_id):
    person = get_person_for_public(user["public_uuid"], person_id)
    if not person:
        abort(404)

    qr_uri = qr_data_uri(person)

    body = render_template_string(
        """
        <section class="hero">
          <span class="badge">Public balance page</span>
          <h1>{{ initials(person['first_name'], person['last_name']) }}</h1>
          <p class="sub">Adjust this balance using the buttons below. Positive means this person owes the owner. Negative means the owner owes this person.</p>
        </section>

        <div class="grid grid-2">
          <div class="card stack-lg">
            <div class="split">
              <div>
                <h2>Current balance</h2>
                <p class="muted">Visible on the public page.</p>
              </div>
              <div class="avatar">{{ initials(person['first_name'], person['last_name']) }}</div>
            </div>

            <div class="metric {% if person['balance_cents'] > 0 %}positive{% elif person['balance_cents'] < 0 %}negative{% else %}zero{% endif %}">
              {{ format_currency(person['balance_cents']) }}
            </div>

            <form class="stack" method="post" action="/public/{{ user.public_uuid }}/people/{{ person['id'] }}/adjust">
              <label>
                Amount
                <input name="amount" inputmode="decimal" placeholder="100" required>
              </label>
              <div class="actions">
                <button type="submit" name="action" value="add">Add amount</button>
                <button type="submit" name="action" value="subtract" class="secondary">Subtract amount</button>
              </div>
            </form>

            <div class="actions">
              <a class="button ghost" href="/public/{{ user.public_uuid }}">Back to initials</a>
            </div>
          </div>

          <div class="card stack-lg">
            <div>
              <h2>Swish</h2>
              <p class="muted">QR code image uploaded by the owner.</p>
            </div>
            <div class="qr-box">
              {% if qr_uri %}
                <img src="{{ qr_uri }}" alt="Swish QR code">
              {% else %}
                <div class="muted">No Swish QR uploaded yet</div>
              {% endif %}
            </div>
          </div>
        </div>
        """,
        user=user,
        person=person,
        qr_uri=qr_uri,
        initials=initials,
        format_currency=format_currency,
    )
    return render_page("Public person page", body)


@app.post("/public/<public_uuid>/people/<int:person_id>/adjust")
@require_public_user
def adjust_person_public(user, person_id):
    person = get_person_for_public(user["public_uuid"], person_id)
    if not person:
        abort(404)

    action = (request.form.get("action") or "").strip().lower()
    try:
        amount_cents = parse_amount_to_cents(request.form.get("amount"))
    except ValueError as exc:
        return render_message_page(
            "Invalid amount",
            str(exc),
            f"/public/{user['public_uuid']}/people/{person_id}",
            is_error=True,
        )

    delta = amount_cents if action == "add" else -amount_cents
    with get_conn() as conn:
        conn.execute(
            "UPDATE people SET balance_cents = balance_cents + ? WHERE id = ?",
            (delta, person_id),
        )

    return redirect(url_for("public_person", public_uuid=user["public_uuid"], person_id=person_id))


def render_message_page(title: str, message: str, back_href: str, is_error: bool = False):
    body = render_template_string(
        """
        <section class="hero">
          <span class="badge">{{ 'Something went wrong' if is_error else 'Done' }}</span>
          <h1>{{ title }}</h1>
          <p class="sub">{{ message }}</p>
        </section>

        <div class="actions">
          <a class="button" href="{{ back_href }}">Go back</a>
          <a class="button secondary" href="/">Home</a>
        </div>
        """,
        title=title,
        message=message,
        back_href=back_href,
        is_error=is_error,
    )
    return render_page(title, body), (400 if is_error else 200)


if __name__ == "__main__":
    init_db()
    host = os.environ.get("APP_HOST", "0.0.0.0")
    port = int(os.environ.get("APP_PORT", "8000"))
    debug = os.environ.get("APP_DEBUG", "").strip() == "1"
    print(f"Starting UUID Balance App on http://{host}:{port}")
    print(f"SQLite database: {DB_PATH}")
    app.run(host=host, port=port, debug=debug)
