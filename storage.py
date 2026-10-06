"""Tiny JSON storage for ElderGuard.

Only alert history is saved to disk (data/alerts.json). Live sensor state
stays in memory so the project stays easy to understand and reset.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

ALERT_FILE = Path(__file__).resolve().parent / "data" / "alerts.json"
_lock = threading.Lock()


def _read_alerts() -> list[dict[str, Any]]:
    ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        return json.loads(ALERT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _write_alerts(alerts: list[dict[str, Any]]) -> None:
    # Write to a temp file first so an interrupted save cannot corrupt data.
    temp_file = ALERT_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(alerts, indent=2), encoding="utf-8")
    os.replace(temp_file, ALERT_FILE)


def load_alerts() -> list[dict[str, Any]]:
    """Return alert history, newest first."""
    with _lock:
        return list(reversed(_read_alerts()))


def add_alert(alert: dict[str, Any]) -> None:
    with _lock:
        alerts = _read_alerts()
        alerts.append(alert)
        _write_alerts(alerts)


def acknowledge_alert(alert_id: str, caretaker: str, acknowledged_at: str) -> dict[str, Any] | None:
    """Mark one alert as acknowledged and return it, or None if not found."""
    with _lock:
        alerts = _read_alerts()
        for alert in alerts:
            if alert.get("id") == alert_id:
                alert.update(acknowledged=True, acknowledged_by=caretaker, acknowledged_at=acknowledged_at)
                _write_alerts(alerts)
                return alert
        return None
