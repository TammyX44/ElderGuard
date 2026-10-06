"""Explainable monitoring agent for ElderGuard.

Three syllabus ideas live in this one small file:
1. Binary Step / threshold decision — each vital becomes 0 (normal) or 1 (abnormal).
2. Simple Reflex Agent — the current condition maps straight to an action.
3. Model-Based Reflex Agent — the last five binary checks are remembered, so a
   persistent problem counts more than a single spike.

Everything is a visible rule on purpose; there is no black-box model.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from config import NEURON_INPUTS, NEURON_THRESHOLD, THRESHOLDS

STATUS_ORDER = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}
MEMORY_SIZE = 5      # past checks remembered per vital
PERSISTENT_MIN = 3   # abnormal in at least 3 of the last 5 checks = persistent

# Persistent abnormality raises concern by one level.
ESCALATION = {"NORMAL": "WATCH", "WATCH": "WARNING", "WARNING": "CRITICAL", "CRITICAL": "CRITICAL"}

ACTION_FOR_STATUS = {
    "NORMAL": "Continue monitoring",
    "WATCH": "Show watch status on dashboard",
    "WARNING": "Create warning incident and notify dashboard",
    "CRITICAL": "Create critical incident and notify caretaker",
}


def binary_step(x: float) -> int:
    """Binary Step Function: 1 when x >= 0, otherwise 0."""
    return 1 if x >= 0 else 0


def severity_outside(value: float, vital: dict) -> tuple[str, int]:
    """Status + binary flag for vitals that have both a low and high limit."""
    low_normal, high_normal = vital["normal"]
    abnormal = binary_step(max(low_normal - value, value - high_normal))

    if value <= vital["critical"][0] or value >= vital["critical"][1]:
        return "CRITICAL", abnormal
    if value <= vital["warning"][0] or value >= vital["warning"][1]:
        return "WARNING", abnormal
    if abnormal:
        return "WATCH", abnormal
    return "NORMAL", abnormal


def severity_below(value: float, vital: dict) -> tuple[str, int]:
    """Status + binary flag for vitals that only have a minimum (SpO₂)."""
    abnormal = binary_step(vital["normal_min"] - value)
    if value <= vital["critical_min"]:
        return "CRITICAL", abnormal
    if value <= vital["warning_min"]:
        return "WARNING", abnormal
    if abnormal:
        return "WATCH", abnormal
    return "NORMAL", abnormal


def _check_vitals(vitals: dict[str, float]) -> dict[str, dict[str, Any]]:
    """Run every threshold check once and collect status + binary flag."""
    results = {}

    for key in ("heart_rate", "temperature"):
        results[key] = dict(zip(("status", "abnormal"), severity_outside(vitals[key], THRESHOLDS[key])))

    results["spo2"] = dict(zip(("status", "abnormal"), severity_below(vitals["spo2"], THRESHOLDS["spo2"])))

    # Blood pressure is judged from the worse of its two numbers.
    systolic_status, systolic_bad = severity_outside(vitals["systolic"], THRESHOLDS["systolic"])
    diastolic_status, diastolic_bad = severity_outside(vitals["diastolic"], THRESHOLDS["diastolic"])
    worst = max((systolic_status, diastolic_status), key=STATUS_ORDER.get)
    results["blood_pressure"] = {"status": worst, "abnormal": 1 if (systolic_bad or diastolic_bad) else 0}

    return results


class MonitoringAgent:
    """Small explainable decision engine for one or more patients."""

    def __init__(self) -> None:
        self.memories: dict[str, dict[str, deque[int]]] = {}

    def evaluate(self, patient_id: str, vitals: dict[str, float]) -> dict[str, Any]:
        results = _check_vitals(vitals)

        # Model-based part: remember the last five binary decisions per vital.
        memory = self.memories.setdefault(
            patient_id, {key: deque(maxlen=MEMORY_SIZE) for key in results}
        )
        for key, result in results.items():
            readings = memory[key]
            readings.append(result["abnormal"])
            result["history"] = list(readings)
            result["persistent"] = len(readings) >= PERSISTENT_MIN and sum(readings) >= PERSISTENT_MIN

        # Simple reflex part: worst current status decides the overall status,
        # then persistent problems raise it by one level.
        overall = max((r["status"] for r in results.values()), key=STATUS_ORDER.get)
        if any(r["persistent"] for r in results.values()):
            overall = ESCALATION[overall]
        if sum(r["abnormal"] for r in results.values()) >= 2 and STATUS_ORDER[overall] < STATUS_ORDER["WARNING"]:
            overall = "WARNING"

        return {
            "status": overall,
            "risk_score": self._risk_score(results),
            "action": ACTION_FOR_STATUS[overall],
            "reasons": self._build_reasons(vitals, results),
            "vital_results": results,
            "neuron": self._neuron_view(results),
        }

    @staticmethod
    def _risk_score(results: dict[str, dict[str, Any]]) -> int:
        """Transparent priority score (rule-based, not an ML prediction)."""
        points = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}
        max_severity = max(points[r["status"]] for r in results.values())
        abnormal_count = sum(r["abnormal"] for r in results.values())
        persistent_count = sum(1 for r in results.values() if r["persistent"])

        score = max_severity * 22 + abnormal_count * 5 + persistent_count * 10
        return min(100, score)

    @staticmethod
    def _build_reasons(vitals: dict[str, float], results: dict[str, dict[str, Any]]) -> list[str]:
        labels = {
            "heart_rate": f"Heart rate is {vitals['heart_rate']:.0f} BPM",
            "spo2": f"SpO\u2082 is {vitals['spo2']:.0f}%",
            "temperature": f"Temperature is {vitals['temperature']:.1f}\u00b0C",
            "blood_pressure": f"Blood pressure is {vitals['systolic']:.0f}/{vitals['diastolic']:.0f} mmHg",
        }

        reasons = []
        for key, result in results.items():
            if result["abnormal"]:
                reasons.append(f"{labels[key]} \u2014 outside the configured normal threshold")
            if result["persistent"]:
                count = sum(result["history"])
                reasons.append(f"{key.replace('_', ' ').title()}: {count} of the last {len(result['history'])} checks were abnormal")

        return reasons[:6] or ["All monitored vitals are inside the configured demonstration thresholds"]

    @staticmethod
    def _neuron_view(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """McCulloch-Pitts view of the same decision: y = step(w.x - theta).

        x is 1 when the vital is abnormal right now OR has become persistent
        (3 of the last 5 checks), so this view always matches the escalation.
        """
        inputs = [
            {
                "key": key,
                "label": spec["label"],
                "x": 1 if (results[key]["abnormal"] or results[key]["persistent"]) else 0,
                "currently_abnormal": bool(results[key]["abnormal"]),
                "persistent": bool(results[key]["persistent"]),
                "w": spec["w"],
            }
            for key, spec in NEURON_INPUTS.items()
        ]
        weighted_sum = round(sum(item["x"] * item["w"] for item in inputs), 1)
        return {
            "inputs": inputs,
            "sum": weighted_sum,
            "theta": NEURON_THRESHOLD,
            "output": binary_step(weighted_sum - NEURON_THRESHOLD),
        }
