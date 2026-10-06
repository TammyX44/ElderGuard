"""Telegram notification adapter for ElderGuard.

The caretaker can configure Telegram from the browser. Credentials are stored
locally in data/telegram_settings.json for this classroom prototype. Environment
variables still work as fallbacks.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parent / "data" / "telegram_settings.json"


def _load_settings() -> dict:
    settings = {"bot_token": "", "chat_id": ""}
    if SETTINGS_PATH.exists():
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                settings["bot_token"] = str(raw.get("bot_token", "")).strip()
                settings["chat_id"] = str(raw.get("chat_id", "")).strip()
        except (OSError, json.JSONDecodeError):
            pass

    # Environment values are useful for deployment and remain valid fallbacks.
    settings["bot_token"] = settings["bot_token"] or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    settings["chat_id"] = settings["chat_id"] or os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return settings


def get_telegram_settings(mask_token: bool = True) -> dict:
    settings = _load_settings()
    token = settings["bot_token"]
    if mask_token and token:
        visible = token[-6:] if len(token) > 6 else token[-2:]
        token_display = "••••••••••" + visible
    else:
        token_display = token
    return {
        "bot_token": token_display,
        "chat_id": settings["chat_id"],
        "configured": bool(token and settings["chat_id"]),
        "has_token": bool(token),
    }


def save_telegram_settings(bot_token: str | None = None, chat_id: str | None = None) -> dict:
    current = _load_settings()
    if bot_token is not None:
        bot_token = bot_token.strip()
        # Empty token means "keep existing" so the masked field never overwrites it.
        if bot_token:
            current["bot_token"] = bot_token
    if chat_id is not None:
        current["chat_id"] = chat_id.strip()

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return get_telegram_settings(mask_token=True)


def telegram_configured() -> bool:
    settings = _load_settings()
    return bool(settings["bot_token"] and settings["chat_id"])


def _telegram_call(method: str, params: dict | None = None, token: str | None = None, timeout: int = 5) -> tuple[bool, dict | str]:
    settings = _load_settings()
    token = (token or settings["bot_token"]).strip()
    if not token:
        return False, "Bot token is not configured"

    url = f"https://api.telegram.org/bot{token}/{method}"
    data = None
    if params is not None:
        data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        if body.get("ok"):
            return True, body
        return False, body.get("description", "Telegram rejected the request")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            return False, body.get("description", f"Telegram HTTP {exc.code}")
        except Exception:
            return False, f"Telegram HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return False, f"Telegram connection error: {exc}"


def test_bot_token(bot_token: str | None = None) -> tuple[bool, dict | str]:
    ok, result = _telegram_call("getMe", token=bot_token)
    if not ok:
        return False, result
    bot = result.get("result", {})
    return True, {
        "id": bot.get("id"),
        "username": bot.get("username", ""),
        "first_name": bot.get("first_name", "Telegram Bot"),
    }


def discover_recent_chats(bot_token: str | None = None) -> tuple[bool, list[dict] | str]:
    """Return unique chats from recent bot updates.

    The caretaker should send /start or any message to the bot first. This is a
    straightforward classroom-friendly way to discover a personal chat ID.
    """
    ok, result = _telegram_call("getUpdates", {"limit": 25, "timeout": 0}, token=bot_token, timeout=6)
    if not ok:
        return False, result

    chats: list[dict] = []
    seen: set[str] = set()
    for update in reversed(result.get("result", [])):
        message = update.get("message") or update.get("edited_message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None or str(chat_id) in seen:
            continue
        seen.add(str(chat_id))
        name = " ".join(part for part in [chat.get("first_name"), chat.get("last_name")] if part).strip()
        name = name or chat.get("title") or chat.get("username") or "Telegram chat"
        chats.append({
            "chat_id": str(chat_id),
            "name": name,
            "username": chat.get("username", ""),
            "type": chat.get("type", ""),
        })
    return True, chats


def send_test_message(chat_id: str | None = None, bot_token: str | None = None) -> tuple[bool, str]:
    settings = _load_settings()
    chat_id = (chat_id or settings["chat_id"]).strip()
    if not chat_id:
        return False, "Chat ID is not configured"
    message = (
        "✅ ElderGuard Telegram test successful\n\n"
        "This caretaker account can receive warning and critical patient alerts.\n"
        "Prototype notification only — not a medical diagnosis."
    )
    ok, result = _telegram_call("sendMessage", {"chat_id": chat_id, "text": message}, token=bot_token)
    return (True, "Test alert sent to Telegram") if ok else (False, str(result))


def send_telegram_alert(alert: dict) -> tuple[bool, str]:
    settings = _load_settings()
    if not settings["bot_token"] or not settings["chat_id"]:
        return False, "Telegram credentials are not configured"

    vitals = alert["vitals"]
    message = (
        f"🚨 ELDERGUARD {alert['status']} ALERT\n\n"
        f"Patient: {alert['patient_name']} ({alert['patient_id']})\n"
        f"Heart Rate: {vitals['heart_rate']} BPM\n"
        f"SpO₂: {vitals['spo2']}%\n"
        f"Temperature: {vitals['temperature']}°C\n"
        f"Blood Pressure: {vitals['systolic']}/{vitals['diastolic']} mmHg\n\n"
        f"Risk Priority: {alert['risk_score']}/100\n"
        f"Reason: {alert['reasons'][0] if alert['reasons'] else 'Abnormal vital pattern'}\n"
        f"Time: {alert['created_at']}\n\n"
        "Prototype monitoring alert — not a medical diagnosis."
    )

    ok, result = _telegram_call("sendMessage", {"chat_id": settings["chat_id"], "text": message})
    return (True, "Telegram message sent") if ok else (False, str(result))
