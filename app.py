"""ElderGuard Flask application.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from agent import MonitoringAgent
from auth import add_account, authenticate, ensure_default_account
from config import ALERT_COOLDOWN_SECONDS, DEMO_LOGIN, SECRET_KEY, THRESHOLDS
from notifier import (
    discover_recent_chats,
    get_telegram_settings,
    save_telegram_settings,
    send_telegram_alert,
    send_test_message,
    telegram_configured,
    test_bot_token,
)
from simulator import PATIENTS, VitalSimulator
from storage import acknowledge_alert, add_alert, load_alerts

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Seed the starter caretaker account (hashed) the first time the app runs.
ensure_default_account(DEMO_LOGIN["email"], DEMO_LOGIN["password"], DEMO_LOGIN["name"])


@app.context_processor
def inject_system_channels():
    """Expose notification-channel status to every authenticated template."""
    return {"telegram_enabled": telegram_configured()}

simulator = VitalSimulator()
agent = MonitoringAgent()

# Small in-memory runtime state: activity feed + notification cooldown.
activity: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=30))
last_status: dict[str, str] = defaultdict(lambda: "NORMAL")
last_alert_at: dict[str, float] = defaultdict(float)
latest_snapshot: dict[str, dict] = {}
latest_snapshot_at: dict[str, float] = defaultdict(float)


def now_label() -> str:
    return datetime.now().strftime("%d %b %Y, %I:%M:%S %p")


def log_activity(patient_id: str, source: str, message: str, level: str = "info") -> None:
    activity[patient_id].appendleft({
        "time": datetime.now().strftime("%H:%M:%S"),
        "source": source,
        "message": message,
        "level": level,
    })


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("caretaker"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def collect_snapshots() -> dict[str, dict]:
    """Update and evaluate every patient once."""
    return {patient_id: build_snapshot(patient_id) for patient_id in PATIENTS}


def attention_count(snapshots: dict[str, dict]) -> int:
    """How many patients are currently WARNING or CRITICAL."""
    return sum(1 for snap in snapshots.values() if snap["decision"]["status"] in {"WARNING", "CRITICAL"})


TIME_FORMAT = "%d %b %Y, %I:%M:%S %p"   # how alert timestamps are stored


def _parse_time(value):
    try:
        return datetime.strptime(value, TIME_FORMAT)
    except (TypeError, ValueError):
        return None


def _format_duration(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    return f"{minutes}m {sec:02d}s"


def build_metrics(alerts: list[dict]) -> dict:
    """Simple caretaking performance numbers computed from incident history."""
    today = datetime.now().date()

    acknowledged = 0
    ack_times = []          # seconds between each alert and its acknowledgement
    alerts_today = 0
    critical = 0
    for alert in alerts:
        created = _parse_time(alert.get("created_at"))
        if created and created.date() == today:
            alerts_today += 1
        if alert.get("status") == "CRITICAL":
            critical += 1
        if alert.get("acknowledged"):
            acknowledged += 1
            closed = _parse_time(alert.get("acknowledged_at"))
            if created and closed and closed >= created:
                ack_times.append((closed - created).total_seconds())

    return {
        "total": len(alerts),
        "today": alerts_today,
        "critical": critical,
        "open": len(alerts) - acknowledged,
        "ack_rate": round(100 * acknowledged / len(alerts)) if alerts else 100,
        "avg_ack": _format_duration(sum(ack_times) / len(ack_times)) if ack_times else "-",
    }


def build_snapshot(patient_id: str) -> dict:
    sim = simulator.update(patient_id)
    decision = agent.evaluate(patient_id, sim["vitals"])
    previous = last_status[patient_id]
    current = decision["status"]

    if previous != current:
        log_activity(patient_id, "AGENT", f"Status changed {previous} → {current}", "critical" if current == "CRITICAL" else "warning" if current == "WARNING" else "info")
    else:
        log_activity(patient_id, "SENSOR", f"New vital set evaluated — {current}")

    if current in {"WARNING", "CRITICAL"}:
        should_alert = (
            current != previous or
            time.time() - last_alert_at[patient_id] >= ALERT_COOLDOWN_SECONDS
        )
        if should_alert:
            alert = create_alert(patient_id, sim, decision)
            last_alert_at[patient_id] = time.time()
            log_activity(patient_id, "ALERT", f"{current.title()} incident created", "critical" if current == "CRITICAL" else "warning")
            if telegram_configured():
                threading.Thread(target=_send_telegram_background, args=(patient_id, alert), daemon=True).start()

    last_status[patient_id] = current

    snapshot = {
        **sim,
        "decision": decision,
        "activity": list(activity[patient_id])[:12],
        "updated_at": datetime.now().strftime("%H:%M:%S"),
    }
    latest_snapshot[patient_id] = snapshot
    latest_snapshot_at[patient_id] = time.time()
    return snapshot


def create_alert(patient_id: str, sim: dict, decision: dict) -> dict:
    patient = PATIENTS[patient_id]
    alert = {
        "id": uuid.uuid4().hex[:12],
        "patient_id": patient_id,
        "patient_name": patient["name"],
        "status": decision["status"],
        "risk_score": decision["risk_score"],
        "reasons": decision["reasons"],
        "action": decision["action"],
        "vitals": sim["vitals"],
        "scenario": sim["scenario"],
        "created_at": now_label(),
        "acknowledged": False,
        "acknowledged_by": None,
        "acknowledged_at": None,
    }
    add_alert(alert)
    return alert


def _send_telegram_background(patient_id: str, alert: dict) -> None:
    ok, message = send_telegram_alert(alert)
    log_activity(patient_id, "TELEGRAM", message, "info" if ok else "warning")


@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("dashboard" if session.get("caretaker") else "login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        user = authenticate(email, password)
        if user:
            session["caretaker"] = user["name"]
            return redirect(url_for("dashboard"))
        error = "Invalid email or password."
    return render_template("login.html", error=error, demo=DEMO_LOGIN)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    snapshots = collect_snapshots()
    hour = datetime.now().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    return render_template(
        "dashboard.html",
        patients=PATIENTS,
        snapshots=snapshots,
        alerts=load_alerts()[:5],
        caretaker=session.get("caretaker"),
        attention_count=attention_count(snapshots),
        greeting=greeting,
        metrics=build_metrics(load_alerts()),
    )


@app.route("/patient/<patient_id>")
@login_required
def patient_detail(patient_id: str):
    if patient_id not in PATIENTS:
        return "Patient not found", 404
    snapshot = build_snapshot(patient_id)
    patient_alerts = [a for a in load_alerts() if a.get("patient_id") == patient_id][:8]
    return render_template(
        "patient.html",
        patient=PATIENTS[patient_id],
        snapshot=snapshot,
        alerts=patient_alerts,
        thresholds=THRESHOLDS,
    )


@app.route("/simulation")
@login_required
def simulation_page():
    requested_patient = request.args.get("patient", "P001")
    patient_id = requested_patient if requested_patient in PATIENTS else "P001"
    snapshot = build_snapshot(patient_id)
    return render_template(
        "simulation.html",
        patients=PATIENTS,
        selected_patient=PATIENTS[patient_id],
        snapshot=snapshot,
    )




@app.route("/notifications")
@login_required
def notification_settings_page():
    return render_template("notifications.html", telegram=get_telegram_settings(mask_token=True))


@app.route("/api/dashboard-state")
@login_required
def api_dashboard_state():
    """Return every patient snapshot and live dashboard summary in one request.

    One endpoint (instead of one request per card) keeps the caretaker board
    reliably in sync and avoids race conditions between separate polls.
    """
    snapshots = collect_snapshots()
    alerts = load_alerts()
    recent_alerts = [
        {
            "id": alert.get("id"),
            "patient_id": alert.get("patient_id"),
            "patient_name": alert.get("patient_name"),
            "status": alert.get("status"),
            "reason": (alert.get("reasons") or [alert.get("action", "Incident")])[0],
            "acknowledged": bool(alert.get("acknowledged")),
        }
        for alert in alerts[:5]
    ]
    return jsonify({
        "snapshots": snapshots,
        "summary": {
            "patients": len(PATIENTS),
            "attention": attention_count(snapshots),
            "open_incidents": sum(1 for alert in alerts if not alert.get("acknowledged")),
            "telegram_enabled": telegram_configured(),
        },
        "metrics": build_metrics(alerts),
        "recent_alerts": recent_alerts,
    })


@app.route("/api/telegram/settings", methods=["GET", "POST"])
@login_required
def api_telegram_settings():
    if request.method == "GET":
        return jsonify(get_telegram_settings(mask_token=True))
    payload = request.get_json(silent=True) or {}
    token = payload.get("bot_token")
    chat_id = payload.get("chat_id")
    settings = save_telegram_settings(bot_token=token, chat_id=chat_id)
    return jsonify({"ok": True, "settings": settings})


@app.route("/api/telegram/test-bot", methods=["POST"])
@login_required
def api_telegram_test_bot():
    payload = request.get_json(silent=True) or {}
    token = (payload.get("bot_token") or "").strip() or None
    ok, result = test_bot_token(token)
    return jsonify({"ok": ok, "bot": result if ok else None, "message": None if ok else result}), (200 if ok else 400)


@app.route("/api/telegram/discover-chats", methods=["POST"])
@login_required
def api_telegram_discover_chats():
    payload = request.get_json(silent=True) or {}
    token = (payload.get("bot_token") or "").strip() or None
    ok, result = discover_recent_chats(token)
    if not ok:
        return jsonify({"ok": False, "message": result}), 400
    return jsonify({"ok": True, "chats": result})


@app.route("/api/telegram/test-alert", methods=["POST"])
@login_required
def api_telegram_test_alert():
    payload = request.get_json(silent=True) or {}
    token = (payload.get("bot_token") or "").strip() or None
    chat_id = (payload.get("chat_id") or "").strip() or None
    ok, message = send_test_message(chat_id=chat_id, bot_token=token)
    return jsonify({"ok": ok, "message": message}), (200 if ok else 400)


@app.route("/api/caretakers/add", methods=["POST"])
@login_required
def api_add_caretaker():
    """Create a new caretaker login from the Notifications page."""
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""

    if not name or "@" not in email or len(password) < 6:
        return jsonify({
            "ok": False,
            "message": "Enter a display name, a valid email, and a password of at least 6 characters.",
        }), 400
    if not add_account(email, password, name):
        return jsonify({"ok": False, "message": "An account with this email already exists."}), 400
    return jsonify({"ok": True, "message": f"Account created for {name} ({email}). They can sign in now."})


@app.route("/alerts")
@login_required
def alerts_page():
    return render_template("alerts.html", alerts=load_alerts())


@app.route("/api/live/<patient_id>")
@login_required
def api_live(patient_id: str):
    if patient_id not in PATIENTS:
        return jsonify({"error": "Patient not found"}), 404
    return jsonify(build_snapshot(patient_id))


@app.route("/api/simulate/<patient_id>", methods=["POST"])
@login_required
def api_simulate(patient_id: str):
    if patient_id not in PATIENTS:
        return jsonify({"error": "Patient not found"}), 404

    payload = request.get_json(silent=True) or {}
    scenario = payload.get("scenario", "normal")
    allowed = {"normal", "heart_rate_spike", "low_oxygen", "fever", "bp_spike", "multi_vital", "recovery"}
    if scenario not in allowed:
        return jsonify({"error": "Unknown scenario"}), 400

    intensity = payload.get("intensity", "moderate")
    duration = payload.get("duration", 30)
    simulator.set_scenario(patient_id, scenario, intensity, duration)
    log_activity(patient_id, "SIM", f"Scenario started: {scenario.replace('_', ' ').title()} ({intensity})")
    return jsonify({"ok": True, "scenario": scenario, "intensity": intensity, "duration": duration})


@app.route("/api/notification-feed")
@login_required
def api_notification_feed():
    """Small polling feed used by the browser Notification API.

    The browser remembers which alert IDs it has already shown, so this
    endpoint can stay stateless and simple for a classroom Flask demo.
    """
    feed = [
        {
            "id": alert.get("id"),
            "patient_id": alert.get("patient_id"),
            "patient_name": alert.get("patient_name"),
            "status": alert.get("status"),
            "risk_score": alert.get("risk_score"),
            "reasons": alert.get("reasons", []),
            "created_at": alert.get("created_at"),
            "vitals": alert.get("vitals", {}),
            "acknowledged": bool(alert.get("acknowledged")),
        }
        for alert in load_alerts()[:12]
    ]
    # Live status per patient, so the browser alarm reflects how patients
    # are RIGHT NOW instead of old unacknowledged incidents. Reuse a fresh
    # snapshot from page polling; refresh only if it is older than 5s.
    current_statuses = {}
    for patient_id in PATIENTS:
        if _is_fresh(patient_id):
            current_statuses[patient_id] = latest_snapshot[patient_id]["decision"]["status"]
        else:
            current_statuses[patient_id] = build_snapshot(patient_id)["decision"]["status"]

    return jsonify({
        "alerts": feed,
        "telegram_enabled": telegram_configured(),
        "current_statuses": current_statuses,
    })


def _is_fresh(patient_id: str) -> bool:
    return time.time() - latest_snapshot_at.get(patient_id, 0) < 5


@app.route("/api/alerts/<alert_id>/acknowledge", methods=["POST"])
@login_required
def api_acknowledge(alert_id: str):
    caretaker = session.get("caretaker", "Caretaker")
    acknowledged_at = now_label()
    updated = acknowledge_alert(alert_id, caretaker, acknowledged_at)
    if not updated:
        return jsonify({"error": "Alert not found"}), 404
    log_activity(updated["patient_id"], "CARE", f"Alert acknowledged by {caretaker}")
    return jsonify({"ok": True, "alert": updated})


if __name__ == "__main__":
    print("ElderGuard running at http://127.0.0.1:5000")
    print(f"Demo login: {DEMO_LOGIN['email']} / {DEMO_LOGIN['password']}")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
