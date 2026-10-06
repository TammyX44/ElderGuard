"""Small configuration module for ElderGuard.

The thresholds below are demonstration thresholds for a college prototype.
They are not medical diagnostic rules and should not be used for clinical care.
"""

import os

SECRET_KEY = os.getenv("ELDERGUARD_SECRET_KEY", "elderguard-demo-secret-change-me")

DEMO_LOGIN = {
    "email": os.getenv("ELDERGUARD_DEMO_EMAIL", "caretaker@elderguard.local"),
    "password": os.getenv("ELDERGUARD_DEMO_PASSWORD", "demo123"),
    "name": "Demo Caretaker",
}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Used only to prevent repeated notification spam while a condition stays abnormal.
ALERT_COOLDOWN_SECONDS = 45

# Demonstration thresholds. All values are intentionally configurable.
THRESHOLDS = {
    "heart_rate": {
        "label": "Heart Rate",
        "unit": "BPM",
        "normal": (60, 100),
        "warning": (50, 115),
        "critical": (40, 130),
    },
    "spo2": {
        "label": "SpO₂",
        "unit": "%",
        "normal_min": 95,
        "warning_min": 92,
        "critical_min": 89,
    },
    "temperature": {
        "label": "Temperature",
        "unit": "°C",
        "normal": (36.0, 37.4),
        "warning": (35.4, 38.2),
        "critical": (34.8, 39.0),
    },
    "systolic": {
        "label": "Systolic BP",
        "unit": "mmHg",
        "normal": (100, 139),
        "warning": (90, 159),
        "critical": (80, 179),
    },
    "diastolic": {
        "label": "Diastolic BP",
        "unit": "mmHg",
        "normal": (60, 89),
        "warning": (55, 99),
        "critical": (50, 109),
    },
}

# McCulloch-Pitts style neuron used for the transparent "neuron view" panel.
# Each monitored vital is one binary input x (the abnormal flag from the
# threshold check), w is its importance weight, and the neuron fires when the
# weighted sum S reaches theta. This makes the agent's core decision visible.
NEURON_INPUTS = {
    "heart_rate": {"label": "Heart rate", "w": 1.5},
    "spo2": {"label": "SpO₂", "w": 2.0},
    "temperature": {"label": "Temperature", "w": 1.2},
    "blood_pressure": {"label": "Blood pressure", "w": 1.3},
}
NEURON_THRESHOLD = 2.0
