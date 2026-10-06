"""Stateful, smooth vital-sign simulator for the ElderGuard demo.

Vitals drift gently toward a target instead of jumping randomly, so the live
graphs look like real signals. A scenario (for example "fever") moves one or
more vitals toward a target value, holds there, then partially recovers.
"""

from __future__ import annotations

import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

BASELINES = {
    "P001": {"heart_rate": 76.0, "spo2": 97.5, "temperature": 36.7, "systolic": 122.0, "diastolic": 78.0},
    "P002": {"heart_rate": 72.0, "spo2": 98.0, "temperature": 36.5, "systolic": 118.0, "diastolic": 74.0},
    "P003": {"heart_rate": 81.0, "spo2": 96.8, "temperature": 36.8, "systolic": 128.0, "diastolic": 82.0},
    "P004": {"heart_rate": 69.0, "spo2": 97.2, "temperature": 36.6, "systolic": 116.0, "diastolic": 72.0},
}

PATIENTS = {
    "P001": {"id": "P001", "name": "Arun Mehta", "age": 76, "room": "Home A-12"},
    "P002": {"id": "P002", "name": "Meera Rao", "age": 81, "room": "Home B-04"},
    "P003": {"id": "P003", "name": "Dev Khanna", "age": 73, "room": "Home A-08"},
    "P004": {"id": "P004", "name": "Nisha Iyer", "age": 79, "room": "Home C-02"},
}

INTENSITY = {"mild": 0.65, "moderate": 1.0, "severe": 1.28}

SCENARIO_TARGETS = {
    "heart_rate_spike": {"heart_rate": 138.0},
    "low_oxygen": {"spo2": 87.0},
    "fever": {"temperature": 39.2},
    "bp_spike": {"systolic": 184.0, "diastolic": 112.0},
    "multi_vital": {"heart_rate": 142.0, "spo2": 86.0, "temperature": 38.7, "systolic": 176.0, "diastolic": 108.0},
}

# Per-vital signal character used when preloading history so graphs are not empty.
# key: (wave speed, wave size, random jitter)
WAVES = {
    "heart_rate": (1.0, 1.6, 0.55),
    "spo2": (0.7, 0.12, 0.06),
    "temperature": (0.35, 0.025, 0.0),
    "systolic": (0.55, 0.8, 0.25),
    "diastolic": (0.55, 0.5, 0.18),
}

# Small realistic-looking noise added on every update (simulation only).
JITTER = {
    "heart_rate": 1.4,
    "spo2": 0.18,
    "temperature": 0.025,
    "systolic": 0.8,
    "diastolic": 0.6,
}

# Sensible simulation bounds per vital: (minimum, maximum).
LIMITS = {
    "heart_rate": (35, 180),
    "spo2": (78, 100),
    "temperature": (33.5, 41.5),
    "systolic": (70, 210),
    "diastolic": (42, 130),
}


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _event_factor(progress: float) -> float:
    """Smooth ramp up, hold, then partial recovery during one scenario."""
    if progress < 0.28:
        return _smoothstep(progress / 0.28)
    if progress < 0.72:
        return 1.0
    return 1.0 - 0.65 * _smoothstep((progress - 0.72) / 0.28)


@dataclass
class PatientState:
    patient_id: str
    vitals: dict[str, float]
    scenario: str = "normal"
    intensity: str = "moderate"
    scenario_started: float = 0.0
    scenario_duration: float = 30.0
    last_update: float = field(default_factory=time.time)
    history: dict[str, deque[float]] = field(default_factory=dict)


class VitalSimulator:
    def __init__(self) -> None:
        self.states: dict[str, PatientState] = {}
        for patient_id, baseline in BASELINES.items():
            state = PatientState(patient_id=patient_id, vitals=dict(baseline))
            # Preload a short stable history so the live graph is visible on
            # the first render instead of waiting for several API polls.
            state.history = {key: deque(maxlen=40) for key in baseline}
            for sample_index in range(30):
                phase = sample_index / 4.5
                for key, value in baseline.items():
                    speed, size, jitter = WAVES[key]
                    sample = value + math.sin(phase * speed) * size
                    if jitter:
                        sample += random.uniform(-jitter, jitter)
                    state.history[key].append(sample)
            self.states[patient_id] = state

    def set_scenario(self, patient_id: str, scenario: str, intensity: str = "moderate", duration: int = 30) -> None:
        state = self.states[patient_id]
        state.scenario = scenario
        state.intensity = intensity if intensity in INTENSITY else "moderate"
        state.scenario_duration = max(10, min(120, int(duration)))
        state.scenario_started = time.time()

    def _next_vitals(self, state: PatientState, dt: float) -> None:
        baseline = BASELINES[state.patient_id]
        targets = SCENARIO_TARGETS.get(state.scenario, {})
        scale = INTENSITY.get(state.intensity, 1.0)

        factor = 0.0
        if state.scenario != "normal" and state.scenario_started:
            progress = (time.time() - state.scenario_started) / state.scenario_duration
            if progress >= 1.0:
                state.scenario = "normal"          # scenario finished on its own
                state.scenario_started = 0.0
            else:
                factor = _event_factor(progress)

        # How strongly vitals are pulled toward their desired value this tick.
        pull = {"normal": 0.20, "recovery": 0.42}.get(state.scenario, 0.28)

        for key, base in baseline.items():
            desired = base
            if state.scenario != "recovery" and key in targets:
                desired = base + (targets[key] - base) * factor * scale

            state.vitals[key] += (desired - state.vitals[key]) * pull * dt
            state.vitals[key] += random.uniform(-JITTER[key], JITTER[key])
            low, high = LIMITS[key]
            state.vitals[key] = min(high, max(low, state.vitals[key]))

    def update(self, patient_id: str) -> dict[str, Any]:
        state = self.states[patient_id]
        now = time.time()
        dt = max(0.3, min(3.0, now - state.last_update))   # seconds since last poll
        state.last_update = now

        self._next_vitals(state, dt)

        for key, value in state.vitals.items():
            state.history[key].append(value)

        display = {
            "heart_rate": round(state.vitals["heart_rate"]),
            "spo2": round(state.vitals["spo2"], 1),
            "temperature": round(state.vitals["temperature"], 1),
            "systolic": round(state.vitals["systolic"]),
            "diastolic": round(state.vitals["diastolic"]),
        }
        histories = {key: [round(v, 1) for v in values] for key, values in state.history.items()}

        return {
            "patient": PATIENTS[patient_id],
            "vitals": display,
            "history": histories,
            "scenario": state.scenario,
            "intensity": state.intensity,
        }
