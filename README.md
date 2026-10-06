# ElderGuard

**Explainable AI-assisted elderly monitoring and caregiver alert system**

ElderGuard is a Flask web app that simulates live vitals for elderly patients, runs them through a small explainable monitoring agent, escalates abnormal conditions, and alerts a caretaker in the browser, on the desktop, and on Telegram.

Every decision is a visible rule. When a status changes, the app shows why.

> **Education and simulation only.** The thresholds are demonstration values. They are not clinical limits and this is not medical advice.

---

## Features

| Area | What it does |
| --- | --- |
| **Caretaker console** | All assigned patients on one screen with live status, vitals, priority score and performance metrics |
| **Live vitals** | Heart rate, SpO₂, temperature and blood pressure, updated continuously |
| **Status escalation** | Normal → Watch → Warning → Critical |
| **Patient record** | Live vital cards, SVG trend chart, "Why this status?" reasoning, neuron view and five-check memory |
| **Simulation Lab** | Trigger heart-rate spike, low oxygen, fever, BP elevation or multi-vital emergency at mild, moderate or severe intensity |
| **Incidents** | Full alert history with caretaker acknowledgement |
| **Notifications** | In-app toasts, native desktop notifications (Web Notifications API) and Telegram alerts for Warning and Critical incidents |
| **Accounts** | Caretaker login with salted PBKDF2-SHA256 password hashes |
| **Theme** | Light and dark mode, remembered per browser |

No database server, Node toolchain or ML training pipeline. Flask is the only dependency.

---

## How the agent decides

All the logic is in [`agent.py`](agent.py), and every threshold is in [`config.py`](config.py).

1. **Binary step threshold.** Each vital becomes `0` (normal) or `1` (abnormal).
2. **Simple reflex agent.** The current condition maps straight to an action, for example *create critical incident and notify caretaker*.
3. **Model-based reflex agent.** The last five checks per vital are remembered. A vital that is abnormal in at least 3 of 5 checks counts as persistent and raises the status by one level, so a single noisy reading doesn't page anyone.
4. **McCulloch–Pitts neuron view.** Each vital's abnormal flag is weighted (SpO₂ 2.0, heart rate 1.5, BP 1.3, temperature 1.2). The neuron fires when the weighted sum reaches θ = 2.0, which makes the core decision visible on screen.
5. **Priority score (0–100).** A transparent rule-based score that ranks incidents for the caretaker. It is not an ML prediction.

```text
sensor percept → threshold check → memory → status + reasons → action → notify
```

### Default thresholds

| Vital | Normal | Warning | Critical |
| --- | --- | --- | --- |
| Heart rate (BPM) | 60–100 | 50–115 | 40–130 |
| SpO₂ (%) | ≥ 95 | ≥ 92 | ≥ 89 |
| Temperature (°C) | 36.0–37.4 | 35.4–38.2 | 34.8–39.0 |
| Systolic BP (mmHg) | 100–139 | 90–159 | 80–179 |
| Diastolic BP (mmHg) | 60–89 | 55–99 | 50–109 |

Readings outside the critical range are Critical.

---

## Getting started

**Requirements:** Python 3.10+

```bash
git clone https://github.com/TammyX44/ElderGuard.git
cd ElderGuard
python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

Install and run:

```bash
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000** and sign in with the demo account:

```text
Email:    caretaker@elderguard.local
Password: demo123
```

The demo account is created automatically on first run. To add more caretakers:

```bash
python auth.py add ravi@elderguard.local "Ravi Sharma" s3cret
```

---

## Configuration

Copy `.env.example` to `.env`, or set the variables in your shell. All of them are optional.

| Variable | Purpose |
| --- | --- |
| `ELDERGUARD_SECRET_KEY` | Flask session secret. Change it for any real deployment |
| `ELDERGUARD_DEMO_EMAIL` / `ELDERGUARD_DEMO_PASSWORD` | Demo caretaker credentials |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Enables Telegram alerts |

### Desktop notifications

1. Sign in.
2. Click **Enable desktop alerts** in the sidebar and allow the browser prompt.
3. Keep the tab open. New Warning and Critical incidents show a native notification, and clicking it opens the affected patient.

These use the standard Web Notifications API, so they work while the browser is running. Use HTTPS if you deploy publicly.

### Telegram alerts

1. Create a bot with **@BotFather** and copy the token.
2. Send your bot a message.
3. Open the **Notifications** page in ElderGuard, paste the token, find your chat ID and send a test alert. You can also set the environment variables above instead.

Example alert:

```text
🚨 ELDERGUARD CRITICAL ALERT

Patient: Arun Mehta (P001)
Heart Rate: 139 BPM
SpO₂: 87%
Temperature: 38.7°C
Blood Pressure: 176/108 mmHg

Risk Priority: 100/100
Reason: Heart rate is outside the configured normal threshold
```

Settings saved from the Notifications page are stored in `data/telegram_settings.json`, which is git-ignored.

---

## Demo walkthrough

1. Sign in and open the **Caretaker** console with the four simulated patients.
2. Go to **Simulation Lab**, pick **P001 – Arun Mehta** and run **Heart-rate spike**.
3. Open the patient record and point out the trend chart, the status escalation and the "Why this status?" panel.
4. Run **Multi-vital emergency** to reach Critical. The toast, desktop notification and Telegram alert fire.
5. Open **Incidents** and acknowledge the alert.
6. Run **Return patient to normal**.

---

## Project structure

```text
ElderGuard/
├── app.py            # Flask routes, background monitor loop, JSON APIs
├── agent.py          # Explainable monitoring agent (threshold, reflex, memory, neuron)
├── simulator.py      # Smooth vital-sign simulator and scenarios
├── notifier.py       # Telegram + browser notification feed
├── auth.py           # Caretaker accounts (PBKDF2 hashed)
├── storage.py        # JSON alert history
├── config.py         # Thresholds, weights, settings
├── requirements.txt
├── .env.example
├── data/             # Runtime JSON files (created automatically, git-ignored)
├── templates/        # Jinja pages: login, dashboard, patient, simulation, alerts, notifications
└── static/
    ├── css/style.css
    └── js/dashboard.js
```

---

## Design choices

- **Why not BFS, DFS or A\*?** Monitoring is a condition → response problem, not path-finding.
- **Why no neural network?** The thresholds and actions are already known. A trained model would add data, evaluation and black-box behaviour without improving the result. ML fits better as a later step once real long-term sensor data exists.
- **Why JSON files and no database?** It keeps the project easy to run, read and reset.

## Possible next steps

- Connect real wearable or IoT sensor data
- Web Push so alerts arrive with the browser closed
- Per-patient thresholds set by a clinician
- SQLite or Postgres storage

## License

Released for educational use. Add a license file if you plan to distribute it.
