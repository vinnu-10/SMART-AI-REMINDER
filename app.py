# app.py
"""
AI Reminder Agent — updated:
- Removed manual date/time fields (use natural text only)
- Pastel theme across pages
- Speech recognition enabled for the 'When' field (microphone)
- Keeps Flask-SocketIO and APScheduler
"""
import os
import sqlite3
from datetime import datetime, timedelta
from flask import (
    Flask, request, render_template_string, redirect, url_for,
    flash, jsonify, session
)
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import smtplib
from email.mime.text import MIMEText
from apscheduler.schedulers.background import BackgroundScheduler
import dateparser
from flask_socketio import SocketIO
import eventlet

load_dotenv()

# Config
DB_PATH = os.getenv("REMINDER_DB", "reminders.db")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
FLASK_SECRET = os.getenv("FLASK_SECRET", "devsecret")
PORT = int(os.getenv("PORT", 5000))

# Optional Gemini: safe import (won't crash if absent)
try:
    from google import generativeai as genai
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if GEMINI_API_KEY:
        try:
            genai.configure(api_key=GEMINI_API_KEY)
        except Exception:
            genai = None
    else:
        genai = None
except Exception:
    genai = None

app = Flask(__name__)
app.secret_key = FLASK_SECRET
socketio = SocketIO(app, async_mode="eventlet")
scheduler = BackgroundScheduler()
scheduler.start()

# ---------------- DB helpers ----------------
def get_db_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT,
        description TEXT,
        email TEXT,
        next_run TEXT,
        recurrence TEXT,
        sent INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

def ensure_columns():
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA table_info(reminders)")
        rows = cur.fetchall()
        names = [r["name"] for r in rows]
        if "user_id" not in names:
            try:
                cur.execute("ALTER TABLE reminders ADD COLUMN user_id INTEGER;")
            except Exception:
                pass
        if "sent" not in names:
            try:
                cur.execute("ALTER TABLE reminders ADD COLUMN sent INTEGER DEFAULT 0;")
            except Exception:
                pass
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

# ---------------- Auth ----------------
def create_user(email, password):
    conn = get_db_conn()
    cur = conn.cursor()
    pw_hash = generate_password_hash(password)
    try:
        cur.execute("INSERT INTO users (email, password_hash) VALUES (?,?)", (email, pw_hash))
        conn.commit()
        uid = cur.lastrowid
    except sqlite3.IntegrityError:
        uid = None
    conn.close()
    return uid

def authenticate_user(email, password):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()
    if row and check_password_hash(row["password_hash"], password):
        return row["id"]
    return None

def get_user(uid):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, email, created_at FROM users WHERE id = ?", (uid,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

# ---------------- Reminders ----------------
def add_reminder(user_id, title, description, email_to, next_run_dt, recurrence):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reminders (user_id, title, description, email, next_run, recurrence) VALUES (?,?,?,?,?,?)",
        (user_id, title, description, email_to, next_run_dt.isoformat() if next_run_dt else None, recurrence)
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid

def list_user_reminders(user_id):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM reminders WHERE user_id = ? ORDER BY next_run", (user_id,))
    rows = cur.fetchall()
    conn.close()
    items = []
    for r in rows:
        rdict = dict(r)
        if rdict.get("next_run"):
            try:
                rdict["next_run"] = datetime.fromisoformat(rdict["next_run"])
            except Exception:
                rdict["next_run"] = None
        else:
            rdict["next_run"] = None
        rdict["sent"] = int(rdict.get("sent") or 0)
        items.append(rdict)
    return items

def get_reminder(rid):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM reminders WHERE id = ?", (rid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["next_run"] = datetime.fromisoformat(d["next_run"]) if d.get("next_run") else None
    d["sent"] = int(d.get("sent") or 0)
    return d

def update_next_run(rid, next_dt):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("UPDATE reminders SET next_run = ? WHERE id = ?", (next_dt.isoformat() if next_dt else None, rid))
    conn.commit()
    conn.close()

def mark_sent(rid):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("UPDATE reminders SET sent = 1, next_run = NULL WHERE id = ?", (rid,))
    conn.commit()
    conn.close()

# ---------------- Email ----------------
def send_email(subject, body, to_email):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        return False, "Email not configured."
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = to_email
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=20)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, [to_email], msg.as_string())
        server.quit()
        return True, f"Email sent to {to_email}"
    except Exception as e:
        return False, str(e)

# ---------------- Scheduling ----------------
def compute_next_run_from(recurrence, from_dt: datetime):
    if not recurrence or recurrence == "none":
        return None
    if recurrence == "daily":
        return from_dt + timedelta(days=1)
    if recurrence.startswith("weekly:"):
        days = recurrence.split(":", 1)[1].split(",")
        daymap = {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}
        nums = [daymap.get(d.strip().lower()[:3]) for d in days]
        nums = [n for n in nums if n is not None]
        candidate = from_dt + timedelta(days=1)
        for i in range(0,14):
            if candidate.weekday() in nums:
                return candidate
            candidate += timedelta(days=1)
    return None

def schedule_job_for(rem):
    if not rem.get("next_run"):
        return
    job_id = f"rem_{rem['id']}"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    scheduler.add_job(func=send_reminder_job, trigger="date", run_date=rem["next_run"], args=[rem["id"]], id=job_id)

def reschedule_all():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM reminders WHERE next_run IS NOT NULL")
    rows = cur.fetchall()
    conn.close()
    for r in rows:
        rem = dict(r)
        try:
            rem["next_run"] = datetime.fromisoformat(rem["next_run"]) if rem.get("next_run") else None
        except Exception:
            rem["next_run"] = None
        rem["sent"] = int(rem.get("sent") or 0)
        if rem["next_run"]:
            schedule_job_for(rem)

def send_reminder_job(rid):
    app.logger.info(f"Firing reminder {rid}")
    rem = get_reminder(rid)
    if not rem:
        return
    subject = f"Reminder: {rem.get('title') or 'Reminder'}"
    body = rem.get("description") or ""
    ok, status = (False, "No recipient")
    if rem.get("email"):
        ok, status = send_email(subject, body, rem.get("email"))
    app.logger.info(f"Email status: {status}")
    payload = {
        "id": rem["id"],
        "title": rem.get("title"),
        "description": rem.get("description"),
        "user_id": rem.get("user_id"),
        "status": status
    }
    try:
        socketio.emit("reminder_fired", payload, broadcast=True)
    except Exception:
        app.logger.exception("Socket emit failed")
    if rem.get("recurrence") and rem["recurrence"] != "none":
        next_run = compute_next_run_from(rem["recurrence"], rem["next_run"] or datetime.now())
        if next_run:
            update_next_run(rid, next_run)
            newrem = get_reminder(rid)
            schedule_job_for(newrem)
    else:
        mark_sent(rid)

# ---------------- Helpers ----------------
def parse_datetime_from_input(text):
    if not text:
        return None
    # Prefer future interpretations to avoid accidentally parsing past dates.
    try:
        dt = dateparser.parse(text, settings={'PREFER_DATES_FROM': 'future'})
        return dt
    except Exception:
        return None

# ---------------- Templates (pastel theme) ----------------
BASE_HEAD = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
<style>
/* Pastel theme */
:root{
  --bg:#f8f6f2;
  --card:#fffaf6;
  --muted:#7d7a7a;
  --accent:#ffd6e0; /* peach-pink */
  --accent2:#dff7ea; /* mint */
  --accent3:#e9e6ff; /* lavender */
  --btn:#ffb3c6;
  --shadow: 0 6px 18px rgba(20,20,30,0.06);
}
body{ background: linear-gradient(180deg, var(--bg), #ffffff); color:#2b2b2b; }
.card{ background:var(--card); border: none; border-radius:16px; box-shadow:var(--shadow); }
.btn-primary{ background: linear-gradient(90deg,var(--btn), #ffced6); border:none; color:#2b2b2b; font-weight:600; border-radius:10px; }
.btn-outline-primary{ border-radius:10px; }
.navbar{ background:transparent; }
.form-control{ border-radius:10px; }
.small-muted{ color:var(--muted); }
.header-accent{ padding:12px 18px; border-radius:12px; background:linear-gradient(90deg,var(--accent3),var(--accent2)); color:#2b2b2b; display:inline-block; box-shadow:0 4px 14px rgba(0,0,0,0.03); }
.mic-btn{ border-radius:8px; padding:6px 10px; background:transparent; border:1px dashed rgba(0,0,0,0.08); }
.rem-box{ background:linear-gradient(180deg,#ffffff, #fff9f6); padding:12px; border-radius:10px; }
</style>
"""

INDEX_HTML = """
<!doctype html>
<html>
<head>
<title>AI Reminder - Home</title>
""" + BASE_HEAD + """
</head>
<body>
<div class="container py-5">
  <div class="card shadow-sm">
    <div class="card-body text-center">
      <h1 class="card-title">AI Reminder Agent</h1>
      <p class="lead small-muted">Secure voice-driven reminders with email notifications.</p>
      <div class="mt-3">
        <a class="btn btn-primary me-2" href="/signup">Sign Up</a>
        <a class="btn btn-outline-primary" href="/login">Sign In</a>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""

SIGNUP_HTML = """
<!doctype html>
<html>
<head>
<title>Sign Up</title>
""" + BASE_HEAD + """
</head>
<body>
<div class="container py-5">
  <div class="card mx-auto" style="max-width:540px;">
    <div class="card-body">
      <h4>Create account <span class="header-accent">Welcome</span></h4>
      {% with messages = get_flashed_messages() %}
        {% if messages %}{% for m in messages %}<div class="alert alert-warning">{{ m }}</div>{% endfor %}{% endif %}
      {% endwith %}
      <form method="POST">
        <div class="mb-3"><label class="form-label">Email</label><input class="form-control" type="email" name="email" required></div>
        <div class="mb-3"><label class="form-label">Password</label><input class="form-control" type="password" name="password" required></div>
        <button class="btn btn-primary" type="submit">Sign Up</button>
        <a class="btn btn-link" href="/login">Sign in</a>
      </form>
    </div>
  </div>
</div>
</body>
</html>
"""

LOGIN_HTML = """
<!doctype html>
<html>
<head>
<title>Sign In</title>
""" + BASE_HEAD + """
</head>
<body>
<div class="container py-5">
  <div class="card mx-auto" style="max-width:540px;">
    <div class="card-body">
      <h4>Sign in</h4>
      {% with messages = get_flashed_messages() %}
        {% if messages %}{% for m in messages %}<div class="alert alert-warning">{{ m }}</div>{% endfor %}{% endif %}
      {% endwith %}
      <form method="POST">
        <div class="mb-3"><label class="form-label">Email</label><input class="form-control" type="email" name="email" required></div>
        <div class="mb-3"><label class="form-label">Password</label><input class="form-control" type="password" name="password" required></div>
        <button class="btn btn-primary" type="submit">Sign In</button>
        <a class="btn btn-link" href="/signup">Sign up</a>
      </form>
    </div>
  </div>
</div>
</body>
</html>
"""

DASH_HTML = """
<!doctype html>
<html>
<head>
<title>Dashboard</title>
""" + BASE_HEAD + """
</head>
<body>
<nav class="navbar navbar-expand-lg">
  <div class="container-fluid">
    <a class="navbar-brand" href="#">AI Reminder</a>
    <div class="d-flex">
      <span class="me-3 small-muted">{{ user.email }}</span>
      <a class="btn btn-outline-secondary btn-sm" href="/logout">Logout</a>
    </div>
  </div>
</nav>
<div class="container py-4">
  <div class="row g-3">
    <div class="col-md-6">
      <div class="card">
        <div class="card-body">
          <h5>Create Reminder</h5>
          <p class="text-muted">Speak a command or type natural text like "tomorrow 9am call mom".</p>

          <!-- Primary voice button for parsing (title/description/when/email) -->
          <button id="voice-parse-btn" class="btn mic-btn mb-2">🎤 Speak command (auto-parse)</button>
          <div id="voice-status" class="mb-2 small-muted"></div>

          <form id="remform" method="POST" action="/create">
            <div class="mb-2"><label class="form-label">Title</label><input class="form-control" name="title" id="title" placeholder="Optional short title"></div>
            <div class="mb-2"><label class="form-label">Description</label><textarea class="form-control" name="description" id="description" rows="3" placeholder="What to remind about"></textarea></div>

            <div class="mb-2"><label class="form-label">Recipient Email</label><input class="form-control" type="email" name="email" id="email" placeholder="Optional recipient email"></div>

            <div class="mb-2">
              <label class="form-label">When (natural text)</label>
              <div class="d-flex">
                <input class="form-control" name="when_text" id="when_text" placeholder='e.g., "tomorrow 9am" or "next monday 6pm"'>
                <button type="button" id="when-mic" class="btn mic-btn ms-2">🎙️</button>
              </div>
              <div class="small-muted mt-1">Tip: be specific, e.g., "tomorrow at 6pm" or "Oct 30 9:30 am".</div>
            </div>

            <div class="mb-2"><label class="form-label">Recurrence</label>
              <select class="form-select" name="recurrence" id="recurrence">
                <option value="none">None</option>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
              </select>
            </div>

            <div id="weekday-box" class="mb-2" style="display:none">
              <label class="form-check form-check-inline"><input class="form-check-input" type="checkbox" name="weekday" value="Mon">Mon</label>
              <label class="form-check form-check-inline"><input class="form-check-input" type="checkbox" name="weekday" value="Tue">Tue</label>
              <label class="form-check form-check-inline"><input class="form-check-input" type="checkbox" name="weekday" value="Wed">Wed</label>
              <label class="form-check form-check-inline"><input class="form-check-input" type="checkbox" name="weekday" value="Thu">Thu</label>
              <label class="form-check form-check-inline"><input class="form-check-input" type="checkbox" name="weekday" value="Fri">Fri</label>
              <label class="form-check form-check-inline"><input class="form-check-input" type="checkbox" name="weekday" value="Sat">Sat</label>
              <label class="form-check form-check-inline"><input class="form-check-input" type="checkbox" name="weekday" value="Sun">Sun</label>
            </div>

            <div class="mb-2">Occurrences: <input class="form-control d-inline-block" style="width:120px" type="number" name="occurrences" min="1" value="1"> Interval days: <input class="form-control d-inline-block" style="width:120px" type="number" name="interval_days" min="1" value="1"></div>

            <button class="btn btn-primary mt-2" type="submit">Submit Reminder</button>
          </form>
        </div>
      </div>
    </div>

    <div class="col-md-6">
      <div class="card">
        <div class="card-body">
          <h5>Your reminders</h5>
          <div class="mb-2 small-muted">Submitted: <strong>{{ stats.created }}</strong> &nbsp; Sent: <strong>{{ stats.sent }}</strong> &nbsp; Pending: <strong>{{ stats.pending }}</strong></div>
          <div style="max-height:520px; overflow:auto">
            {% for r in reminders %}
            <div class="rem-box mb-2">
              <div><strong>{{ r.title or '(no title)' }}</strong> <span class="small-muted">- {{ r.next_run.strftime('%Y-%m-%d %H:%M') if r.next_run else 'Completed' }}</span></div>
              <div class="text-muted small">{{ r.description }}</div>
              <div class="small">Email: {{ r.email or '-' }} | Sent: {{ 'Yes' if r.sent else 'No' }}</div>
            </div>
            {% else %}
            <div class="small-muted">No reminders yet.</div>
            {% endfor %}
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
// UI JS: voice parsing, when-field voice, recurrence toggle, socket
const voiceParseBtn = document.getElementById('voice-parse-btn');
const whenMic = document.getElementById('when-mic');
const voiceStatus = document.getElementById('voice-status');
const recSelect = document.getElementById('recurrence');
const weekdayBox = document.getElementById('weekday-box');
recSelect.addEventListener('change', ()=>{ weekdayBox.style.display = (recSelect.value==='weekly')? 'block':'none'; });

// helper to start recognition and return transcript via a Promise
function recognizeSpeech(lang='en-US'){
  return new Promise((resolve, reject)=>{
    if (!('SpeechRecognition' in window) && !('webkitSpeechRecognition' in window)){
      reject(new Error('SpeechRecognition not supported'));
      return;
    }
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const r = new SpeechRecognition();
    r.lang = lang;
    r.interimResults = false;
    r.maxAlternatives = 1;
    r.onresult = (ev)=>{
      const transcript = ev.results[0][0].transcript;
      resolve(transcript);
    };
    r.onerror = (ev)=> reject(ev.error || new Error('speech error'));
    r.onend = ()=> {};
    try{ r.start(); }catch(e){ reject(e); }
  });
}

// Voice parse (fills multiple fields using /parse)
voiceParseBtn.addEventListener('click', async ()=>{
  voiceStatus.textContent = 'Listening...';
  try{
    await navigator.mediaDevices.getUserMedia({audio:true});
  }catch(e){ voiceStatus.textContent = 'Microphone permission denied.'; return; }
  try{
    const spoken = await recognizeSpeech();
    voiceStatus.textContent = 'Processing...';
    // call parse endpoint
    const res = await fetch('/parse',{method:'POST',headers:{'Content-Type':'application/json'},body: JSON.stringify({text:spoken})});
    const js = await res.json();
    if (js.parsed){
      const p = js.parsed;
      if (p.title) document.getElementById('title').value = p.title;
      if (p.description) document.getElementById('description').value = p.description;
      if (p.when) document.getElementById('when_text').value = p.when;
      if (p.email) document.getElementById('email').value = p.email;
      if (p.recurrence && p.recurrence.startsWith('weekly')){ recSelect.value='weekly'; weekdayBox.style.display='block'; }
    } else {
      // fallback: put spoken into when_text
      document.getElementById('when_text').value = spoken;
    }
    voiceStatus.textContent = 'Done.';
  }catch(e){
    console.warn(e);
    voiceStatus.textContent = 'Voice parse failed.';
  }
});

// When-field microphone (only fills when_text)
whenMic.addEventListener('click', async ()=>{
  voiceStatus.textContent = 'Listening for time...';
  try{
    await navigator.mediaDevices.getUserMedia({audio:true});
  }catch(e){ voiceStatus.textContent = 'Microphone permission denied.'; return; }
  try{
    const spoken = await recognizeSpeech();
    document.getElementById('when_text').value = spoken;
    voiceStatus.textContent = 'Captured.';
  }catch(e){
    console.warn(e);
    voiceStatus.textContent = 'Speech recognition failed.';
  }
});

// Socket: show notification only for current user
const socket = io();
socket.on('reminder_fired',(payload)=>{
  const currentUser = {{ user.id }};
  if (payload.user_id !== currentUser) return;
  if (Notification && Notification.permission !== 'granted') Notification.requestPermission();
  if (Notification && Notification.permission === 'granted') new Notification(payload.title||'Reminder',{body:payload.description||''}); else alert((payload.title||'Reminder')+'\\n'+(payload.description||''));
  if ('speechSynthesis' in window){ const u = new SpeechSynthesisUtterance((payload.title?payload.title+'. ':'')+(payload.description||'')); speechSynthesis.speak(u); }
  setTimeout(()=>location.reload(),1500);
});
</script>
</body>
</html>
"""

SUBMITTED_HTML = """
<!doctype html>
<html>
<head>
<title>Reminders Submitted</title>
""" + BASE_HEAD + """
</head>
<body>
<div class="container py-5">
  <div class="card mx-auto" style="max-width:800px;">
    <div class="card-body">
      <h4>Submission Summary</h4>
      <p class="mb-1">You have submitted <strong>{{ created }}</strong> reminders.</p>
      <p class="mb-1">Sent: <strong>{{ sent }}</strong></p>
      <p class="mb-3">Pending: <strong>{{ pending }}</strong></p>
      <a class="btn btn-primary" href="/thankyou">Proceed</a>
      <a class="btn btn-link" href="/dashboard">Back to Dashboard</a>
    </div>
  </div>
</div>
</body>
</html>
"""

THANKYOU_HTML = """
<!doctype html>
<html>
<head>
<title>Thank you</title>
""" + BASE_HEAD + """
</head>
<body>
<div class="container py-5">
  <div class="card mx-auto" style="max-width:700px;">
    <div class="card-body text-center">
      <h3>Thank you!</h3>
      <p>Your reminders were received and scheduled. You may close this window or return to the dashboard.</p>
      <a class="btn btn-primary" href="/dashboard">Back to Dashboard</a>
    </div>
  </div>
</div>
</body>
</html>
"""

# ---------------- Routes ----------------
def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper

@app.route("/")
def index():
    return render_template_string(INDEX_HTML)

@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        if not email or not password:
            flash("Email and password required")
            return redirect(url_for("signup"))
        uid = create_user(email, password)
        if not uid:
            flash("Account already exists")
            return redirect(url_for("signup"))
        session["user_id"] = uid
        return redirect(url_for("dashboard"))
    return render_template_string(SIGNUP_HTML)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        uid = authenticate_user(email, password)
        if not uid:
            flash("Invalid credentials")
            return redirect(url_for("login"))
        session["user_id"] = uid
        return redirect(url_for("dashboard"))
    return render_template_string(LOGIN_HTML)

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]
    user = get_user(uid)
    reminders = list_user_reminders(uid)
    created = len(reminders)
    sent = sum(1 for r in reminders if r.get("sent"))
    pending = sum(1 for r in reminders if (not r.get("sent") and r.get("next_run")))
    stats = {"created": created, "sent": sent, "pending": pending}
    return render_template_string(DASH_HTML, user=user, reminders=reminders, stats=stats)

@app.route("/create", methods=["POST"])
@login_required
def create():
    uid = session["user_id"]
    title = request.form.get("title","")
    description = request.form.get("description","")
    email_to = request.form.get("email","")
    when_text = request.form.get("when_text","")
    recurrence = request.form.get("recurrence","none")
    weekdays = request.form.getlist("weekday")
    occurrences = int(request.form.get("occurrences") or 1)
    interval_days = int(request.form.get("interval_days") or 1)

    if recurrence == "weekly" and weekdays:
        recurrence_val = "weekly:" + ",".join(weekdays)
    else:
        recurrence_val = recurrence

    # Parse natural-language time only (no date/time pickers)
    dt = None
    if when_text:
        dt = parse_datetime_from_input(when_text)

    if not dt:
        flash('Could not determine date/time from natural text. Try: "tomorrow 9am" or "Oct 30 6:30pm" or use the microphone.')
        return redirect(url_for("dashboard"))

    now = datetime.now()
    if dt <= now and recurrence_val == "none":
        flash("Selected time is in the past. Choose a future time or set recurrence.")
        return redirect(url_for("dashboard"))

    created_ids = []
    cur_dt = dt
    for i in range(occurrences):
        rid = add_reminder(uid, title, description, email_to, cur_dt, recurrence_val)
        rem = get_reminder(rid)
        schedule_job_for(rem)
        created_ids.append(rid)
        cur_dt = cur_dt + timedelta(days=interval_days)

    reminders = list_user_reminders(uid)
    created = len(reminders)
    sent = sum(1 for r in reminders if r.get("sent"))
    pending = sum(1 for r in reminders if (not r.get("sent") and r.get("next_run")))
    session["last_submit_summary"] = {"created": created, "sent": sent, "pending": pending}
    return redirect(url_for("submitted"))

@app.route("/submitted")
@login_required
def submitted():
    s = session.pop("last_submit_summary", None)
    if not s:
        uid = session["user_id"]
        reminders = list_user_reminders(uid)
        s = {"created": len(reminders), "sent": sum(1 for r in reminders if r.get("sent")), "pending": sum(1 for r in reminders if (not r.get("sent") and r.get("next_run")))}
    return render_template_string(SUBMITTED_HTML, created=s["created"], sent=s["sent"], pending=s["pending"])

@app.route("/thankyou")
@login_required
def thankyou():
    return render_template_string(THANKYOU_HTML)

@app.route("/parse", methods=["POST"])
@login_required
def parse_endpoint():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error":"no text"}), 400

    # If Gemini client is available, use it; otherwise fallback.
    if genai:
        try:
            prompt_template = (
                "You are a JSON extractor. From the user's command extract: title, description, when, recurrence, email.\n"
                "Return only valid JSON with keys: title, description, when, recurrence, email.\n\n"
                "User command:\n"
                "\"\"\"<<USER_TEXT>>\"\"\"\n\n"
                "Example output:\n"
                "{\n"
                "  \"title\": \"Meeting with team\",\n"
                "  \"description\": \"Discuss project progress\",\n"
                "  \"when\": \"2025-10-29 09:00\",\n"
                "  \"recurrence\": \"none\",\n"
                "  \"email\": \"someone@example.com\"\n"
                "}\n"
            )
            prompt = prompt_template.replace("<<USER_TEXT>>", text)
            out = genai.generate_text(model="gemini-2.5-flash", input=prompt, max_output_tokens=512)
            parsed_text = getattr(out, "text", str(out))
            import json, re
            m = re.search(r"(\{.*\})", parsed_text, re.S)
            if m:
                js = json.loads(m.group(1))
            else:
                js = json.loads(parsed_text)
            for k in ("title","description","when","recurrence","email"):
                if k not in js:
                    js[k] = ""
            return jsonify({"parsed": js, "used_gemini": True})
        except Exception:
            app.logger.exception("Gemini parse failed")

    # fallback: put spoken text into description and try to extract a date/time using dateparser
    parsed_when = ""
    try:
        dt = parse_datetime_from_input(text)
        if dt:
            parsed_when = dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        parsed_when = ""
    return jsonify({"parsed":{"title":"","description": text,"when": parsed_when,"recurrence":"none","email":""}, "used_gemini": False})

# ---------------- Startup ----------------
if __name__ == "__main__":
    init_db()
    ensure_columns()
    reschedule_all()
    socketio.run(app, host="0.0.0.0", port=PORT, debug=(os.getenv("FLASK_DEBUG","1")=="1"))
