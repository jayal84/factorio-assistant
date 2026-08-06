"""Small, dependency-free normalization helpers for Factorio telemetry."""

from typing import Any


def normalize_player_health(data: dict[str, Any]) -> dict[str, float]:
    """Return raw HP, maximum HP, and percentage with safe numeric defaults."""
    try:
        current_health = float(data.get("current_health", data.get("health", 0.0)) or 0.0)
    except (TypeError, ValueError):
        current_health = 0.0
    try:
        max_health = float(data.get("max_health", 100.0) or 100.0)
    except (TypeError, ValueError):
        max_health = 100.0
    try:
        health_percent = float(data.get("health_percent") or 0.0)
    except (TypeError, ValueError):
        health_percent = 0.0
    if "health_percent" not in data:
        health_percent = (current_health / max_health * 100.0) if max_health > 0 else 0.0
    return {
        "current_health": current_health,
        "max_health": max_health,
        "health_percent": round(health_percent, 2),
    }
