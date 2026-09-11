"""
Deecoder DevMastery — course server (Flask)

MEMBERS-ONLY SITE: every page, the course APIs, and the video files
themselves require a signed-in account. Unauthenticated visitors are
redirected to /login?next=... and returned to their destination after
signing up / signing in.

Serves the front-end pages, a JSON API for auth + course content
(main + backend course), admin drag & drop video uploads, and streams
videos from ./videos with HTTP Range support (seeking works).

Also provides password-reset (forgot password) and Remember Me session
control integrated with the existing users.json + Flask session system.

Run:
    pip install flask
    python app.py
    → http://127.0.0.1:5000
"""

import json
import os
import re
import secrets
import shutil
import smtplib
import hashlib
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
from pathlib import Path
from urllib.parse import quote

from flask import (Flask, abort, jsonify, redirect, request, send_file,
                   send_from_directory, session)
from markupsafe import escape
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent


def _load_env_file():
    """Load .env into os.environ for local/dev only.

    Production (PythonAnywhere, etc.) should set MAIL_* in the host's
    environment variables / secrets. Existing os.environ keys are never
    overwritten, so production values always win over a .env file.
    """
    env_path = BASE / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except OSError:
        pass


_load_env_file()

VIDEO_DIR = BASE / "videos"
COURSE_FILE = BASE / "course.json"
BACKEND_FILE = BASE / "backend-course.json"
TECH_FILE = BASE / "tech-course.json"
DEVOPS_FILE = BASE / "devops-course.json"
AI_FILE = BASE / "ai-course.json"
SECURITY_FILE = BASE / "security-course.json"
DATABASE_FILE = BASE / "database-course.json"
USERS_FILE = BASE / "users.json"
ADMIN_FILE = BASE / "admin.json"
SECRET_FILE = BASE / "secret.key"
RESET_FILE = BASE / "reset_tokens.json"

VIDEO_EXTS = {".mp4", ".webm", ".ogv", ".ogg", ".m4v", ".mov"}
DEFAULT_ADMIN_PASSWORD = "admin123"
API_VERSION = 2          # front-ends check this via /api/health
MAX_UPLOAD_MB = 2048     # per-file upload limit (2 GB)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# Password reset settings (override via env)
RESET_CODE_TTL_SEC = int(os.getenv("RESET_CODE_TTL_SEC", "900"))       # 15 minutes
RESET_TOKEN_TTL_SEC = int(os.getenv("RESET_TOKEN_TTL_SEC", "900"))     # after verify
RESET_RATE_LIMIT_SEC = int(os.getenv("RESET_RATE_LIMIT_SEC", "60"))    # per identifier
RESET_CODE_LENGTH = 6

DEFAULT_COURSE = {
    "courseName": "Advanced React & Micro-Frontends",
    "modules": [
        {"name": "Module 1 · Getting Started", "lessons": [
            {"t": "Welcome — Course Trailer", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "Local sample (put any mp4 in videos/ as sample.mp4)", "d": "—",
             "file": "videos/sample.mp4"},
        ]},
    ],
}


DEFAULT_TECH_COURSE = {
    "courseName": "Technical Engineering Tracks",
    "modules": [
        {"name": "DevOps & Cloud", "lessons": [
            {"t": "Kubernetes, Docker & CI/CD Overview", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "Terraform & AWS foundations (replace in admin)", "d": "—", "v": "klUqEDQFC9c"},
        ]},
        {"name": "AI Engineering", "lessons": [
            {"t": "LLM Integration with Python", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "Vector Databases & PyTorch (replace in admin)", "d": "—", "v": "klUqEDQFC9c"},
        ]},
        {"name": "App Security", "lessons": [
            {"t": "OAuth 2.0 & Secure Coding Basics", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "Penetration Testing intro (replace in admin)", "d": "—", "v": "klUqEDQFC9c"},
        ]},
        {"name": "Database Engineering", "lessons": [
            {"t": "PostgreSQL Optimization", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "Redis & MongoDB patterns (replace in admin)", "d": "—", "v": "klUqEDQFC9c"},
        ]},
    ],
}


DEFAULT_DEVOPS_COURSE = {
    "courseName": "DevOps & Cloud",
    "modules": [
        {"name": "Module 1 · Containers & Orchestration", "lessons": [
            {"t": "Kubernetes fundamentals", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "Docker for production workflows", "d": "—", "v": "klUqEDQFC9c"},
        ]},
        {"name": "Module 2 · Delivery & Cloud", "lessons": [
            {"t": "CI/CD pipelines", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "Terraform & AWS foundations", "d": "—", "v": "klUqEDQFC9c"},
        ]}
    ],
}

DEFAULT_AI_COURSE = {
    "courseName": "AI Engineering",
    "modules": [
        {"name": "Module 1 · LLMs & Python", "lessons": [
            {"t": "LLM integration patterns", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "Python tooling for AI apps", "d": "—", "v": "klUqEDQFC9c"},
        ]},
        {"name": "Module 2 · Data & Models", "lessons": [
            {"t": "Vector databases", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "PyTorch fundamentals", "d": "—", "v": "klUqEDQFC9c"},
        ]}
    ],
}

DEFAULT_SECURITY_COURSE = {
    "courseName": "App Security",
    "modules": [
        {"name": "Module 1 · Auth & Secure Coding", "lessons": [
            {"t": "OAuth 2.0 in practice", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "Secure coding essentials", "d": "—", "v": "klUqEDQFC9c"},
        ]},
        {"name": "Module 2 · Testing", "lessons": [
            {"t": "Penetration testing intro", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "Threat modeling basics", "d": "—", "v": "klUqEDQFC9c"},
        ]}
    ],
}

DEFAULT_DATABASE_COURSE = {
    "courseName": "Database Engineering",
    "modules": [
        {"name": "Module 1 · Relational", "lessons": [
            {"t": "PostgreSQL optimization", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "Indexing & query plans", "d": "—", "v": "klUqEDQFC9c"},
        ]},
        {"name": "Module 2 · Caching & Document stores", "lessons": [
            {"t": "Redis patterns", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "MongoDB data modeling", "d": "—", "v": "klUqEDQFC9c"},
        ]}
    ],
}

DEFAULT_BACKEND_COURSE = {
    "courseName": "Backend Engineering · Go Services & APIs",
    "modules": [
        {"name": "Module 1 · Go Foundations", "lessons": [
            {"t": "Backend Track Trailer (replace me in admin)", "d": "—", "v": "klUqEDQFC9c"},
            {"t": "Local sample (put any mp4 in videos/ as sample.mp4)", "d": "—",
             "file": "videos/sample.mp4"},
        ]},
    ],
}

# ────────────────────────── app setup ──────────────────────────

def _secret_key():
    if SECRET_FILE.exists():
        return SECRET_FILE.read_bytes()
    key = secrets.token_hex(32).encode()
    SECRET_FILE.write_bytes(key)
    return key


app = Flask(__name__)
app.secret_key = _secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
)


@app.after_request
def no_cache_api(resp):
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return resp


@app.errorhandler(413)
def too_large(e):
    return jsonify(error=f"file too large (limit is {MAX_UPLOAD_MB} MB)"), 413


# ────────────────────────── helpers ──────────────────────────

def read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def norm_phone(s):
    return re.sub(r"\D", "", s or "")


def admin_hash():
    data = read_json(ADMIN_FILE, {})
    if "hash" not in data:
        data["hash"] = generate_password_hash(DEFAULT_ADMIN_PASSWORD)
        write_json(ADMIN_FILE, data)
    return data["hash"]


def admin_is_default():
    return check_password_hash(admin_hash(), DEFAULT_ADMIN_PASSWORD)


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            abort(401)
        return fn(*a, **kw)
    return wrapper


def is_authed():
    return bool(session.get("user") or session.get("admin"))


def _login_next():
    nxt = request.full_path if request.query_string else request.path
    if nxt.endswith("?"):
        nxt = nxt[:-1]
    return quote(nxt, safe="")


def page_login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not is_authed():
            return redirect("/login?next=" + _login_next())
        return fn(*a, **kw)
    return wrapper


def api_login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not is_authed():
            abort(401)
        return fn(*a, **kw)
    return wrapper


def load_users():
    data = read_json(USERS_FILE, {"users": []})
    return data if isinstance(data, dict) and isinstance(data.get("users"), list) else {"users": []}


def user_by_username(users, uname):
    return next((u for u in users["users"] if u["username"].lower() == uname.strip().lower()), None)


def user_by_email(users, email):
    e = (email or "").strip().lower()
    return next((u for u in users["users"] if u.get("email") and u["email"] == e), None) if e else None


def user_by_phone(users, phone):
    d = norm_phone(phone)
    return next((u for u in users["users"] if u.get("phone") and u["phone"] == d), None) if d else None


def user_by_identifier(users, ident):
    """Resolve email, phone, or username to a user record."""
    ident = (ident or "").strip()
    if not ident:
        return None
    if "@" in ident:
        return user_by_email(users, ident)
    if re.fullmatch(r"[\d\s()+\-]+", ident):
        return user_by_phone(users, ident) or user_by_username(users, ident)
    return user_by_username(users, ident)


# ────────────────────────── password reset helpers ──────────────────────────

def _hash_code(code):
    return hashlib.sha256((code + app.secret_key.decode() if isinstance(app.secret_key, bytes)
                           else code + str(app.secret_key)).encode()).hexdigest()


def load_resets():
    data = read_json(RESET_FILE, {"tokens": {}})
    if not isinstance(data, dict) or not isinstance(data.get("tokens"), dict):
        return {"tokens": {}}
    return data


def save_resets(data):
    write_json(RESET_FILE, data)


def _purge_expired_resets(data):
    now = time.time()
    dead = [k for k, v in data["tokens"].items()
            if not isinstance(v, dict) or float(v.get("expires", 0)) < now]
    for k in dead:
        data["tokens"].pop(k, None)
    return data



# Email delivery notes (password reset):
# - Sending via smtp.gmail.com as @gmail.com: Google applies its own SPF/DKIM.
# - For a custom domain (e.g. mail@yourdomain.com), configure SPF/DKIM/DMARC at your DNS
#   provider and set MAIL_SERVER / MAIL_FROM / MAIL_USERNAME / MAIL_PASSWORD accordingly.
# - Recipient providers still control Inbox vs Spam; authentication + clean content only help odds.

def _mail_from():
    """Official sender for password-reset emails (override with MAIL_FROM)."""
    return (os.getenv("MAIL_FROM") or "deecoderfrontenddevnationwide@gmail.com").strip()


def _mail_server():
    return (os.getenv("MAIL_SERVER") or "smtp.gmail.com").strip()


def _mail_port():
    return int(os.getenv("MAIL_PORT") or "587")


def _mail_username():
    return (os.getenv("MAIL_USERNAME") or _mail_from()).strip()


def _mail_password():
    """Gmail App Password: env MAIL_PASSWORD wins; built-in default used if unset."""
    return (os.getenv("MAIL_PASSWORD") or "ifpeslyetzbqxpby").strip()


def _mail_use_tls():
    return (os.getenv("MAIL_USE_TLS") or "1") != "0"



def _resend_api_key():
    return (os.getenv("RESEND_API_KEY") or "").strip()


def _send_reset_via_resend(to_email, code, plain, html, subject, mail_from, from_name, reply_to):
    """Transactional send via Resend HTTP API (preferred for inbox delivery)."""
    import json as _json
    import urllib.request
    import urllib.error

    key = _resend_api_key()
    if not key:
        raise RuntimeError("RESEND_API_KEY is not set")

    payload = {
        "from": "%s <%s>" % (from_name, mail_from),
        "to": [to_email],
        "subject": subject,
        "text": plain,
        "html": html,
        "reply_to": reply_to,
        "headers": {
            "Auto-Submitted": "auto-generated",
            "X-Entity-Ref-ID": secrets.token_hex(16),
        },
    }
    data = _json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        method="POST",
        headers={
            "Authorization": "Bearer %s" % key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status >= 300:
                raise RuntimeError("Resend HTTP %s: %s" % (resp.status, body[:200]))
            return body
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError("Resend HTTP %s: %s" % (e.code, err_body[:300]))


def mail_transport():
    """Which transport production will use (no secrets returned)."""
    if _resend_api_key():
        return "resend"
    if _mail_password() and _mail_server():
        return "smtp"
    return "none"


def smtp_configured():
    """True when any password-reset email transport is available."""
    if _resend_api_key():
        return True
    return bool(_mail_server() and _mail_from() and _mail_password())


def twilio_configured():
    return bool(os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN")
                and os.getenv("TWILIO_FROM_NUMBER"))


def send_reset_email(to_email, code):
    """Send password-reset code.

    Prefer Resend (RESEND_API_KEY) for production deliverability with a verified domain.
    Fall back to SMTP (Gmail or other) via MAIL_* env vars.

    Note: Free @gmail.com SMTP often lands in Spam even when authenticated. For reliable
    Inbox placement, use a verified domain on a transactional provider (Resend, SES, etc.).
    Recipient providers still control final placement.
    """
    import uuid
    from email.utils import formatdate, make_msgid

    mail_from = _mail_from()
    from_name = (os.getenv("MAIL_FROM_NAME") or "Deecoder DevMastery").strip()
    reply_to = (os.getenv("MAIL_REPLY_TO") or mail_from).strip()
    mins = max(1, RESET_CODE_TTL_SEC // 60)
    subject = "Your DevMastery password reset code"

    plain = (
        "Deecoder DevMastery\n"
        "\n"
        "We received a request to reset the password for your account.\n"
        "\n"
        "Verification code: %s\n"
        "\n"
        "This code expires in %s minutes and can be used only once.\n"
        "\n"
        "If you did not request a password reset, you can ignore this message.\n"
        "Do not share this code with anyone.\n"
        "\n"
        "— Deecoder DevMastery (automated security message)\n"
    ) % (code, mins)

    html = (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Password reset</title></head>"
        "<body style=\"margin:0;padding:24px;background:#f8fafc;"
        "font-family:Arial,Helvetica,sans-serif;color:#0f172a;font-size:15px;line-height:1.5;\">"
        "<p style=\"margin:0 0 12px 0;\"><strong>Deecoder DevMastery</strong></p>"
        "<p style=\"margin:0 0 12px 0;\">We received a request to reset the password for your account.</p>"
        "<p style=\"margin:0 0 8px 0;\">Verification code:</p>"
        "<p style=\"margin:0 0 16px 0;font-size:22px;font-weight:700;letter-spacing:0.12em;\">%s</p>"
        "<p style=\"margin:0 0 12px 0;color:#475569;\">This code expires in %s minutes and can be used only once.</p>"
        "<p style=\"margin:0 0 12px 0;color:#475569;\">If you did not request a password reset, ignore this message. "
        "Do not share this code with anyone.</p>"
        "<p style=\"margin:16px 0 0 0;color:#94a3b8;font-size:12px;\">"
        "Automated security message from Deecoder DevMastery</p>"
        "</body></html>"
    ) % (code, mins)

    # Prefer transactional API when configured
    if _resend_api_key():
        # From address should be on a domain verified in Resend (not necessarily gmail.com)
        resend_from = (os.getenv("RESEND_FROM") or mail_from).strip()
        _send_reset_via_resend(
            to_email, code, plain, html, subject, resend_from, from_name, reply_to
        )
        app.logger.info("password_reset_email transport=resend to_domain=%s", to_email.split("@")[-1])
        return

    # SMTP fallback (Gmail App Password or other SMTP)
    host = _mail_server()
    port = _mail_port()
    user = _mail_username()
    password = _mail_password()
    use_tls = _mail_use_tls()
    if not password:
        raise RuntimeError("No email transport configured (set RESEND_API_KEY or MAIL_PASSWORD)")

    domain = mail_from.split("@")[-1] if "@" in mail_from else "localhost"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "%s <%s>" % (from_name, mail_from)
    msg["To"] = to_email
    msg["Reply-To"] = reply_to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["MIME-Version"] = "1.0"
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Auto-Response-Suppress"] = "All"
    msg["X-Entity-Ref-ID"] = uuid.uuid4().hex
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")

    try:
        smtp_timeout = max(5, min(20, int(os.getenv("MAIL_SMTP_TIMEOUT", "12"))))
    except ValueError:
        smtp_timeout = 12
    last_err = None

    def _attempt(ssl_mode, p, do_starttls):
        smtp = None
        try:
            if ssl_mode:
                smtp = smtplib.SMTP_SSL(host, p, timeout=smtp_timeout)
            else:
                smtp = smtplib.SMTP(host, p, timeout=smtp_timeout)
            smtp.ehlo()
            if do_starttls and not ssl_mode:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(msg, from_addr=mail_from, to_addrs=[to_email])
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    try:
                        smtp.close()
                    except Exception:
                        pass

    for ssl_mode, p, do_starttls in [(False, port, use_tls)] + ([(True, 465, False)] if port != 465 else []):
        try:
            _attempt(ssl_mode, p, do_starttls)
            app.logger.info(
                "password_reset_email transport=smtp host=%s port=%s ssl=%s to_domain=%s",
                host, p, ssl_mode, to_email.split("@")[-1],
            )
            return
        except (TimeoutError, OSError, smtplib.SMTPException) as exc:
            last_err = exc
            app.logger.warning(
                "password_reset_email smtp_failed host=%s port=%s err=%s",
                host, p, type(exc).__name__,
            )
    raise TimeoutError("Mail server did not respond in time") from last_err



def send_reset_sms(to_phone, code):
    """Send reset code via Twilio REST API (stdlib urllib — no extra dependency)."""
    import base64
    import urllib.request
    import urllib.parse

    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_num = os.getenv("TWILIO_FROM_NUMBER")
    to = to_phone if to_phone.startswith("+") else ("+" + to_phone)

    body = urllib.parse.urlencode({
        "To": to,
        "From": from_num,
        "Body": f"DevMastery reset code: {code}. Expires in {RESET_CODE_TTL_SEC // 60} min.",
    }).encode()

    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=body,
        method="POST",
    )
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=20) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Twilio HTTP {resp.status}")


# ────────────────────────── course loaders ──────────────────────────

def load_named_course(path, default):
    data = read_json(path, None)
    if isinstance(data, dict) and isinstance(data.get("modules"), list):
        return data
    write_json(path, default)
    return json.loads(json.dumps(default))


def load_course():
    return load_named_course(COURSE_FILE, DEFAULT_COURSE)


def sanitize_course(payload):
    if not isinstance(payload, dict):
        return None
    modules = []
    for m in payload.get("modules") or []:
        if not isinstance(m, dict):
            continue
        lessons = []
        for l in m.get("lessons") or []:
            if not isinstance(l, dict):
                continue
            les = {"t": str(l.get("t") or "Untitled lesson")[:120],
                   "d": str(l.get("d") or "—")[:16]}
            if l.get("file"):
                les["file"] = str(l["file"])[:200]
            elif l.get("v"):
                les["v"] = str(l["v"])[:400]
            else:
                continue
            lessons.append(les)
        modules.append({"name": str(m.get("name") or "Module")[:80], "lessons": lessons})
    return {"courseName": str(payload.get("courseName") or "Untitled Course")[:80], "modules": modules}


# ────────────────────────── auth API ──────────────────────────

@app.get("/api/health")
def health():
    return jsonify(ok=True, version=API_VERSION, backendCourse=True, passwordReset=True)


@app.get("/api/auth/me")
def me():
    if session.get("admin"):
        return jsonify(authed=True, username="admin", admin=True)
    uid = session.get("user")
    if not uid:
        return jsonify(authed=False), 401
    u = user_by_username(load_users(), uid)
    if not u:
        session.clear()
        return jsonify(authed=False), 401
    return jsonify(authed=True, username=u["username"], admin=False)


@app.get("/api/auth/available")
def available():
    field = request.args.get("field", "")
    value = (request.args.get("value") or "").strip()
    users = load_users()

    if field == "username":
        if not USERNAME_RE.match(value):
            return jsonify(available=False, reason="3–20 characters: letters, numbers, underscore.")
        if value.lower() in {"admin", "root", "support"}:
            return jsonify(available=False, reason="That username is reserved.")
        if user_by_username(users, value):
            return jsonify(available=False, reason="That username is taken.")
        return jsonify(available=True)

    if field == "email":
        if not EMAIL_RE.match(value):
            return jsonify(available=False, reason="That doesn't look like a valid email.")
        if user_by_email(users, value):
            return jsonify(available=False, reason="That email is already registered.")
        return jsonify(available=True)

    if field == "phone":
        d = norm_phone(value)
        if not (7 <= len(d) <= 15):
            return jsonify(available=False, reason="Need 7–15 digits (include country code).")
        if user_by_phone(users, value):
            return jsonify(available=False, reason="That phone number is already registered.")
        return jsonify(available=True)

    return jsonify(available=False, reason="Unknown field."), 400


@app.post("/api/auth/register")
def register():
    b = request.get_json(silent=True) or {}
    username = (b.get("username") or "").strip()
    password = b.get("password") or ""
    email = (b.get("email") or "").strip().lower()
    phone = norm_phone(b.get("phone"))

    if not USERNAME_RE.match(username):
        return jsonify(error="invalid username"), 400
    if len(password) < 6:
        return jsonify(error="weak password"), 400
    if not email and not phone:
        return jsonify(error="email or phone required"), 400
    if email and not EMAIL_RE.match(email):
        return jsonify(error="invalid email"), 400
    if phone and not (7 <= len(phone) <= 15):
        return jsonify(error="invalid phone"), 400

    users = load_users()
    if (user_by_username(users, username)
            or (email and user_by_email(users, email))
            or (phone and user_by_phone(users, phone))):
        return jsonify(error="already registered"), 409

    users["users"].append({
        "username": username,
        "email": email,
        "phone": phone,
        "password": generate_password_hash(password),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    write_json(USERS_FILE, users)

    session.clear()
    session["user"] = username.lower()
    session.permanent = True
    return jsonify(ok=True, username=username)


@app.post("/api/auth/login")
def login():
    b = request.get_json(silent=True) or {}
    ident = (b.get("identifier") or "").strip()
    password = b.get("password") or ""
    remember = bool(b.get("remember"))
    if not ident or not password:
        return jsonify(error="missing fields"), 400

    users = load_users()
    u = user_by_identifier(users, ident)

    if not u or not check_password_hash(u["password"], password):
        return jsonify(error="bad credentials"), 401

    session.clear()
    session["user"] = u["username"].lower()
    # Remember Me: permanent cookie (30 days) vs browser-session cookie
    session.permanent = remember
    return jsonify(ok=True, username=u["username"], remember=remember)


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


# ── Forgot password ──

@app.post("/api/auth/forgot")
def forgot_request():
    """Step 1: request a reset code — email only."""
    b = request.get_json(silent=True) or {}
    # Accept only email (reject phone / username identifiers)
    email = (b.get("email") or b.get("identifier") or "").strip().lower()
    if not email:
        return jsonify(error="Enter the email address on your account."), 400
    if not EMAIL_RE.match(email):
        return jsonify(error="That doesn't look like a valid email address."), 400
    # Reject pure phone-like input
    if "@" not in email:
        return jsonify(error="Password recovery uses email only. Enter your registered email."), 400

    users = load_users()
    u = user_by_email(users, email)
    if not u or not u.get("email"):
        return jsonify(error="No account found with that email address."), 404

    if not smtp_configured():
        return jsonify(
            error="Email recovery is temporarily unavailable. Contact support at 09016815405."
                  "Set MAIL_PASSWORD (Gmail App Password) for "
                  "deecoderfrontenddevnationwide@gmail.com, or contact support at 09016815405."
        ), 503

    dest = u["email"]
    channel = "email"
    data = _purge_expired_resets(load_resets())
    key = f"{channel}:{dest}"
    existing = data["tokens"].get(key)
    now = time.time()
    if existing and now - float(existing.get("sent_at", 0)) < RESET_RATE_LIMIT_SEC:
        wait = int(RESET_RATE_LIMIT_SEC - (now - float(existing["sent_at"])))
        return jsonify(error=f"Please wait {wait}s before requesting another code."), 429

    code = f"{secrets.randbelow(10 ** RESET_CODE_LENGTH):0{RESET_CODE_LENGTH}d}"
    entry = {
        "username": u["username"].lower(),
        "channel": channel,
        "dest": dest,
        "code_hash": _hash_code(code),
        "expires": now + RESET_CODE_TTL_SEC,
        "sent_at": now,
        "attempts": 0,
        "used": False,
        "reset_token": None,
        "reset_token_expires": None,
    }
    data["tokens"][key] = entry

    try:
        send_reset_email(dest, code)
    except Exception as exc:
        app.logger.exception("Failed to send reset code")
        return jsonify(error="Could not send the verification code. Please try again shortly."), 502

    save_resets(data)
    name, domain = dest.split("@", 1)
    masked = (name[:1] + "***@" + domain) if name else ("***@" + domain)

    return jsonify(
        ok=True,
        channel="email",
        masked=masked,
        expiresIn=RESET_CODE_TTL_SEC,
        message=f"A reset code was sent to {masked}.",
    )


@app.post("/api/auth/forgot/verify")
def forgot_verify():
    """Step 2: verify the code; return a one-time reset_token. Email only."""
    b = request.get_json(silent=True) or {}
    ident = (b.get("identifier") or b.get("email") or "").strip().lower()
    code = (b.get("code") or "").strip().replace(" ", "")
    if not ident or not code:
        return jsonify(error="Enter the code you received."), 400
    if "@" not in ident or not EMAIL_RE.match(ident):
        return jsonify(error="Password recovery uses email only."), 400

    users = load_users()
    u = user_by_email(users, ident)
    channel, dest = "email", (u.get("email") if u else None)

    if not u or not dest:
        return jsonify(error="Invalid or expired code."), 400

    key = f"{channel}:{dest}"
    data = _purge_expired_resets(load_resets())
    entry = data["tokens"].get(key)
    if not entry or entry.get("used"):
        return jsonify(error="Invalid or expired code."), 400
    if float(entry.get("expires", 0)) < time.time():
        return jsonify(error="That code has expired. Request a new one."), 400

    entry["attempts"] = int(entry.get("attempts") or 0) + 1
    if entry["attempts"] > 8:
        data["tokens"].pop(key, None)
        save_resets(data)
        return jsonify(error="Too many attempts. Request a new code."), 429

    if entry.get("code_hash") != _hash_code(code):
        save_resets(data)
        return jsonify(error="Invalid or expired code."), 400

    reset_token = secrets.token_urlsafe(32)
    entry["reset_token"] = _hash_code(reset_token)
    entry["reset_token_expires"] = time.time() + RESET_TOKEN_TTL_SEC
    entry["code_hash"] = ""  # one-time code consumed
    save_resets(data)

    return jsonify(ok=True, resetToken=reset_token, expiresIn=RESET_TOKEN_TTL_SEC)


@app.post("/api/auth/forgot/reset")
def forgot_reset():
    """Step 3: set a new password using the reset token. Email only."""
    b = request.get_json(silent=True) or {}
    reset_token = (b.get("resetToken") or b.get("reset_token") or "").strip()
    password = b.get("password") or ""
    ident = (b.get("identifier") or b.get("email") or "").strip().lower()

    if not reset_token or not password:
        return jsonify(error="Missing token or password."), 400
    if len(password) < 6:
        return jsonify(error="Password must be at least 6 characters."), 400
    if "@" not in ident or not EMAIL_RE.match(ident):
        return jsonify(error="Password recovery uses email only."), 400

    users = load_users()
    u = user_by_email(users, ident)
    channel, dest = "email", (u.get("email") if u else None)

    if not u or not dest:
        return jsonify(error="Invalid or expired reset session."), 400

    key = f"{channel}:{dest}"
    data = _purge_expired_resets(load_resets())
    entry = data["tokens"].get(key)
    if not entry or entry.get("used"):
        return jsonify(error="Invalid or expired reset session."), 400
    if not entry.get("reset_token") or float(entry.get("reset_token_expires") or 0) < time.time():
        return jsonify(error="Invalid or expired reset session."), 400
    if entry["reset_token"] != _hash_code(reset_token):
        return jsonify(error="Invalid or expired reset session."), 400
    if entry.get("username") != u["username"].lower():
        return jsonify(error="Invalid or expired reset session."), 400

    # Update password with same hashing as registration
    for rec in users["users"]:
        if rec["username"].lower() == u["username"].lower():
            rec["password"] = generate_password_hash(password)
            break
    write_json(USERS_FILE, users)

    # Invalidate token
    entry["used"] = True
    entry["reset_token"] = None
    entry["code_hash"] = ""
    save_resets(data)

    return jsonify(ok=True, message="Password updated. You can sign in now.")


# ────────────────────────── course + videos API ──────────────────────────

@app.get("/api/course")
@api_login_required
def get_course():
    return jsonify(load_course())


@app.post("/api/course")
@admin_required
def save_course():
    data = sanitize_course(request.get_json(silent=True))
    if data is None:
        return jsonify(error="bad payload"), 400
    write_json(COURSE_FILE, data)
    n = sum(len(m["lessons"]) for m in data["modules"])
    return jsonify(ok=True, modules=len(data["modules"]), lessons=n)


@app.get("/api/backend-course")
@api_login_required
def get_backend_course():
    return jsonify(load_named_course(BACKEND_FILE, DEFAULT_BACKEND_COURSE))


@app.post("/api/backend-course")
@admin_required
def save_backend_course():
    data = sanitize_course(request.get_json(silent=True))
    if data is None:
        return jsonify(error="bad payload"), 400
    write_json(BACKEND_FILE, data)
    n = sum(len(m["lessons"]) for m in data["modules"])
    return jsonify(ok=True, modules=len(data["modules"]), lessons=n)


@app.get("/api/tech-course")
@api_login_required
def get_tech_course():
    return jsonify(load_named_course(TECH_FILE, DEFAULT_TECH_COURSE))


@app.post("/api/tech-course")
@admin_required
def save_tech_course():
    data = sanitize_course(request.get_json(silent=True))
    if data is None:
        return jsonify(error="bad payload"), 400
    write_json(TECH_FILE, data)
    n = sum(len(m["lessons"]) for m in data["modules"])
    return jsonify(ok=True, modules=len(data["modules"]), lessons=n)

@app.get("/api/devops-course")
@api_login_required
def get_devops_course():
    return jsonify(load_named_course(DEVOPS_FILE, DEFAULT_DEVOPS_COURSE))


@app.post("/api/devops-course")
@admin_required
def save_devops_course():
    data = sanitize_course(request.get_json(silent=True))
    if data is None:
        return jsonify(error="bad payload"), 400
    write_json(DEVOPS_FILE, data)
    n = sum(len(m["lessons"]) for m in data["modules"])
    return jsonify(ok=True, modules=len(data["modules"]), lessons=n)


@app.get("/api/ai-course")
@api_login_required
def get_ai_course():
    return jsonify(load_named_course(AI_FILE, DEFAULT_AI_COURSE))


@app.post("/api/ai-course")
@admin_required
def save_ai_course():
    data = sanitize_course(request.get_json(silent=True))
    if data is None:
        return jsonify(error="bad payload"), 400
    write_json(AI_FILE, data)
    n = sum(len(m["lessons"]) for m in data["modules"])
    return jsonify(ok=True, modules=len(data["modules"]), lessons=n)


@app.get("/api/security-course")
@api_login_required
def get_security_course():
    return jsonify(load_named_course(SECURITY_FILE, DEFAULT_SECURITY_COURSE))


@app.post("/api/security-course")
@admin_required
def save_security_course():
    data = sanitize_course(request.get_json(silent=True))
    if data is None:
        return jsonify(error="bad payload"), 400
    write_json(SECURITY_FILE, data)
    n = sum(len(m["lessons"]) for m in data["modules"])
    return jsonify(ok=True, modules=len(data["modules"]), lessons=n)


@app.get("/api/database-course")
@api_login_required
def get_database_course():
    return jsonify(load_named_course(DATABASE_FILE, DEFAULT_DATABASE_COURSE))


@app.post("/api/database-course")
@admin_required
def save_database_course():
    data = sanitize_course(request.get_json(silent=True))
    if data is None:
        return jsonify(error="bad payload"), 400
    write_json(DATABASE_FILE, data)
    n = sum(len(m["lessons"]) for m in data["modules"])
    return jsonify(ok=True, modules=len(data["modules"]), lessons=n)



@app.get("/api/videos")
def list_videos():
    if not session.get("admin"):
        return jsonify(error="admin session required"), 403
    VIDEO_DIR.mkdir(exist_ok=True)
    files = [{"name": p.name, "size": p.stat().st_size}
             for p in sorted(VIDEO_DIR.iterdir())
             if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    return jsonify(files=files)


@app.post("/api/upload")
@admin_required
def upload_video():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="no file provided"), 400
    name = secure_filename(f.filename)
    if not name:
        return jsonify(error="invalid filename"), 400
    ext = Path(name).suffix.lower()
    if ext not in VIDEO_EXTS:
        return jsonify(error="unsupported file type"), 400

    VIDEO_DIR.mkdir(exist_ok=True)
    stem, suffix = Path(name).stem, Path(name).suffix.lower()
    candidate, i = f"{stem}{suffix}", 1
    while (VIDEO_DIR / candidate).exists():
        candidate = f"{stem}-{i}{suffix}"
        i += 1

    dest = VIDEO_DIR / candidate
    with dest.open("wb") as out:
        shutil.copyfileobj(f.stream, out, length=1024 * 1024)

    return jsonify(ok=True, name=candidate, size=dest.stat().st_size)


@app.get("/videos/<path:filename>")
def video(filename):
    if not is_authed():
        abort(401)
    return send_from_directory(VIDEO_DIR, filename, conditional=True)


@app.post("/api/admin/password")
@admin_required
def change_admin_password():
    b = request.get_json(silent=True) or {}
    if not check_password_hash(admin_hash(), b.get("current") or ""):
        return jsonify(error="wrong current password"), 401
    new = b.get("new") or ""
    if len(new) < 8:
        return jsonify(error="new password too short"), 400
    write_json(ADMIN_FILE, {"hash": generate_password_hash(new)})
    return jsonify(ok=True)


# ────────────────────────── pages ──────────────────────────

@app.get("/")
@page_login_required
def index():
    return send_file(BASE / "index.html")


@app.get("/login")
@app.get("/signup")
def login_page():
    return send_file(BASE / "login.html")


@app.get("/watch")
@page_login_required
def watch_page():
    return send_file(BASE / "watch.html")


@app.get("/watch-backend")
@page_login_required
def watch_backend_page():
    return send_file(BASE / "watch-backend.html")


@app.get("/watch-tech")
@page_login_required
def watch_tech_page():
    return send_file(BASE / "watch-tech.html")

@app.get("/watch-devops")
@page_login_required
def watch_devops_page():
    return send_file(BASE / "watch-devops.html")


@app.get("/watch-ai")
@page_login_required
def watch_ai_page():
    return send_file(BASE / "watch-ai.html")


@app.get("/watch-security")
@page_login_required
def watch_security_page():
    return send_file(BASE / "watch-security.html")


@app.get("/watch-database")
@page_login_required
def watch_database_page():
    return send_file(BASE / "watch-database.html")



@app.get("/dm-api.js")
def dm_api():
    resp = send_file(BASE / "dm-api.js", mimetype="text/javascript")
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


@app.get("/premium.css")
def premium_css():
    path = BASE / "premium.css"
    if not path.exists():
        return ("", 204)
    resp = send_file(path, mimetype="text/css")
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


@app.get("/privacy")
def privacy_page():
    return send_file(BASE / "privacy.html")


@app.get("/terms")
def terms_page():
    return send_file(BASE / "terms.html")


@app.get("/cookies")
def cookies_page():
    return send_file(BASE / "cookies.html")


@app.get("/favicon.ico")
def favicon():
    return ("", 204)


# ────────────────────────── admin ──────────────────────────

ADMIN_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin Sign In | DevMastery</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{--blue:#2563eb;--blue-dark:#1d4ed8;--ink:#0f172a;--border:#e2e8f0}
*{margin:0;padding:0;box-sizing:border-box}
html{font-family:'Inter',sans-serif;color:var(--ink)}
body{background:#f8fafc;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:#fff;border:1px solid var(--border);border-radius:16px;padding:34px 30px;width:100%;max-width:400px;box-shadow:0 20px 25px -5px rgba(15,23,42,.15)}
.logo{font-size:22px;font-weight:800;margin-bottom:4px}.logo span{color:var(--blue)}
h1{font-size:19px;font-weight:800;margin-bottom:6px}
p.sub{font-size:13px;color:#64748b;margin-bottom:18px;line-height:1.55}
label{display:block;font-size:11.5px;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px}
input{width:100%;padding:11px 13px;border:1px solid #cbd5e1;border-radius:8px;font-size:14.5px;outline:none}
input:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(37,99,235,.15)}
button{width:100%;margin-top:14px;padding:13px;background:var(--blue);color:#fff;border:none;border-radius:8px;font-size:15px;font-weight:700;cursor:pointer}
button:hover{background:var(--blue-dark)}
.err{margin-top:14px;font-size:13px;padding:10px 12px;border-radius:8px;background:#fef2f2;border:1px solid #fecaca;color:#991b1b}
.hint{margin-top:14px;background:#fffbeb;border:1px solid #fcd34d;border-radius:10px;padding:11px 13px;font-size:12px;color:#78350f;line-height:1.6}
.row{margin-top:16px;font-size:12.5px}.row a{color:#64748b;text-decoration:none}
</style>
</head>
<body>
<div class="card">
  <div class="logo">Deecoder <span>DevMastery</span></div>
  <h1>Admin sign in</h1>
  <p class="sub">This panel edits the live course content. Session-based — no password prompts while editing.</p>
  <form method="POST" action="/admin">
    <label for="pw">Admin password</label>
    <input id="pw" name="password" type="password" autofocus autocomplete="current-password">
    <button type="submit">Unlock admin panel</button>
  </form>
  __ERR__
  __HINT__
  <div class="row"><a href="/">← Back to home</a></div>
</div>
</body>
</html>"""


def render_admin_login(error="", show_hint=False):
    err = ('<div class="err">✕ ' + escape(error) + "</div>") if error else ""
    hint = ('<div class="hint">🔑 <b>First run:</b> the default admin password is <b>admin123</b>. '
            "Sign in and change it in the “Admin Password” card.</div>") if show_hint else ""
    return ADMIN_LOGIN_HTML.replace("__ERR__", err).replace("__HINT__", hint)


@app.route("/admin", methods=["GET", "POST"])
def admin_page():
    if request.method == "POST":
        pw = request.form.get("password") or ""
        if check_password_hash(admin_hash(), pw):
            session.clear()
            session["admin"] = True
            session.permanent = True
            return redirect("/admin")
        return render_admin_login(error="Wrong password — try again.")
    if session.get("admin"):
        return send_file(BASE / "admin.html")
    return render_admin_login(show_hint=admin_is_default())


# ────────────────────────── boot ──────────────────────────

if __name__ == "__main__":
    # Env already loaded at import via _load_env_file(); production uses host env vars.
    VIDEO_DIR.mkdir(exist_ok=True)
    load_course()
    load_named_course(BACKEND_FILE, DEFAULT_BACKEND_COURSE)
    admin_hash()
    print(
        "\n──────────────────────────────────────────────────────"
        "\n  Deecoder DevMastery  →  http://127.0.0.1:5000"
        "\n    Pages:  /   /watch   /watch-backend   /login   /admin"
        "\n    Access: MEMBERS-ONLY — all pages & videos need sign-in"
        f"\n    Admin password: {'admin123 (default — change it!)' if admin_is_default() else '(changed — stored in admin.json)'}"
        "\n    Courses: course.json (main) · backend-course.json (backend)"
        f"\n    Uploads: drag & drop in admin · {MAX_UPLOAD_MB} MB max per file"
        f"\n    Lesson videos folder: {VIDEO_DIR}"
        f"\n    Mail transport: {mail_transport()}"
        f"\n    Mail reset: {'configured → ' + _mail_from() if smtp_configured() else 'NOT configured (set MAIL_PASSWORD App Password)'}"
        f"\n    SMS reset:  {'configured' if twilio_configured() else 'NOT configured (set TWILIO_*)'}"
        "\n──────────────────────────────────────────────────────\n"
    )
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
