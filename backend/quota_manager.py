"""
PyMentor Local Quota Manager
Tracks Gemini and Gemma API quotas locally to eliminate wasted requests.
Accurately handles:
- Strict model prioritization (Gemini first, Gemma emergency only)
- Daily resets at Pacific Time midnight (Google's quota reset boundary)
- PC sleep, wake, program restarts, and concurrent student requests
- Automatic fallback when local limits or unexpected 429s occur
"""

import time
import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

try:
    from zoneinfo import ZoneInfo
    PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
except Exception:
    PACIFIC_TZ = None

try:
    from pymentor.backend.database import get_connection
except ImportError:
    from backend.database import get_connection

logger = logging.getLogger("pymentor.quota")
_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────
# MODEL CONFIGURATION & PRIORITY
# 1,100 High-Quality Gemini requests per day before Gemma
# Gemma models are strictly LAST RESORT (Emergency only)
# ─────────────────────────────────────────────────────────────
MODEL_CONFIGS: List[Dict[str, Any]] = [
    # ── GUIDANCE-ONLY: high-volume, lower-quality lite models ──
    {
        "model": "gemini-3.5-flash-lite",
        "rpd": 500,
        "rpm": 15,
        "tier": "Gemini Flash Lite (Primary)",
        "priority": 1,
        "uses": "guidance",   # Not good enough for learning reports
    },
    {
        "model": "gemini-3.1-flash-lite",
        "rpd": 500,
        "rpm": 15,
        "tier": "Gemini Flash Lite (Secondary)",
        "priority": 2,
        "uses": "guidance",   # Not good enough for learning reports
    },
    # ── PREMIUM: used for both guidance fallback AND learning reports ──
    {
        "model": "gemini-3.8-flash",
        "rpd": 20,
        "rpm": 5,
        "tier": "Gemini 3.8 Flash (Premium)",
        "priority": 3,
        "uses": "both",       # Report primary, guidance fallback
    },
    {
        "model": "gemini-3.7-flash",
        "rpd": 20,
        "rpm": 5,
        "tier": "Gemini 3.7 Flash (Premium)",
        "priority": 4,
        "uses": "both",
    },
    {
        "model": "gemini-3.6-flash",
        "rpd": 20,
        "rpm": 5,
        "tier": "Gemini 3.6 Flash (Standard)",
        "priority": 5,
        "uses": "both",
    },
    {
        "model": "gemini-3.5-flash",
        "rpd": 20,
        "rpm": 5,
        "tier": "Gemini 3.5 Flash (Standard)",
        "priority": 6,
        "uses": "both",
    },
    {
        "model": "gemini-2.5-flash",
        "rpd": 20,
        "rpm": 5,
        "tier": "Gemini 2.5 Flash (Standard)",
        "priority": 7,
        "uses": "both",
    },
    # ── EMERGENCY SAFETY NET (guidance only — never used for reports) ──
    {
        "model": "gemma-4-31b-it",
        "rpd": 14400,
        "rpm": 30,
        "tier": "Gemma 4 31B (Emergency Fallback 1)",
        "priority": 8,
        "uses": "guidance",   # Never used for learning reports
    },
    {
        "model": "gemma-4-26b-a4b-it",
        "rpd": 14400,
        "rpm": 30,
        "tier": "Gemma 4 26B (Emergency Fallback 2)",
        "priority": 9,
        "uses": "guidance",   # Never used for learning reports
    },
]

MODEL_MAP = {cfg["model"]: cfg for cfg in MODEL_CONFIGS}


def get_pacific_date_str() -> str:
    """Returns YYYY-MM-DD in America/Los_Angeles (Pacific Time)."""
    if PACIFIC_TZ:
        return datetime.now(PACIFIC_TZ).strftime("%Y-%m-%d")
    # Fallback to UTC-7 (Pacific Daylight)
    pt_time = datetime.now(timezone.utc) - timedelta(hours=7)
    return pt_time.strftime("%Y-%m-%d")


def init_quota_tables():
    """Ensure quota tracking table exists in database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS model_quotas (
        model_name TEXT PRIMARY KEY,
        pt_date TEXT NOT NULL,
        day_count INTEGER NOT NULL DEFAULT 0,
        minute_timestamps TEXT NOT NULL DEFAULT '[]',
        is_daily_blocked INTEGER NOT NULL DEFAULT 0,
        last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()


# Initialize on import
init_quota_tables()


def _get_available_for_use(use_filter: str) -> List[str]:
    """
    Core quota logic shared by get_available_models() and get_available_report_models().
    Returns models in priority order that pass the quota check AND match `use_filter`.
    use_filter: 'guidance' → all models (guidance + both)
                'report'   → only models with uses='both'
    """
    current_pt_date = get_pacific_date_str()
    now_ts = time.time()
    cutoff_ts = now_ts - 60.0

    with _lock:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT model_name, pt_date, day_count, minute_timestamps, is_daily_blocked FROM model_quotas")
        rows = {r["model_name"]: dict(r) for r in cursor.fetchall()}

        available = []

        for cfg in MODEL_CONFIGS:
            model = cfg["model"]
            rpd   = cfg["rpd"]
            rpm   = cfg["rpm"]
            uses  = cfg.get("uses", "both")

            # Filter: reports only want models marked 'both'
            if use_filter == "report" and uses != "both":
                continue

            row = rows.get(model)
            if not row:
                available.append(model)
                continue

            pt_date          = row.get("pt_date")
            day_count        = row.get("day_count", 0)
            is_daily_blocked = row.get("is_daily_blocked", 0)

            # New Pacific Time day → reset counters
            if pt_date != current_pt_date:
                cursor.execute("""
                UPDATE model_quotas
                SET pt_date = ?, day_count = 0, minute_timestamps = '[]', is_daily_blocked = 0
                WHERE model_name = ?
                """, (current_pt_date, model))
                conn.commit()
                available.append(model)
                continue

            # Daily quota check
            if is_daily_blocked or day_count >= rpd:
                continue

            # Minute rate-limit check
            try:
                raw_ts   = json.loads(row.get("minute_timestamps") or "[]")
                valid_ts = [ts for ts in raw_ts if ts > cutoff_ts]
            except Exception:
                valid_ts = []

            if len(valid_ts) >= rpm:
                continue

            available.append(model)

        conn.close()
        return available


def get_available_models() -> List[str]:
    """
    Returns guidance-eligible models in priority order (all tiers including flash-lite and Gemma).
    Falls back to Gemma emergency models if every Gemini model is exhausted.
    """
    available = _get_available_for_use("guidance")

    if not available:
        logger.warning("All primary models at quota! Falling back to Gemma emergency models.")
        available = ["gemma-4-31b-it", "gemma-4-26b-a4b-it"]

    return available


def get_available_report_models() -> List[str]:
    """
    Returns premium-only models eligible for learning report generation,
    in priority order (gemini-3.8-flash → 3.7 → 3.6 → 3.5 → 2.5).
    Never includes flash-lite or Gemma — reports must be high quality.
    Returns an empty list if all premium quota is exhausted (caller should raise an error).
    """
    return _get_available_for_use("report")


def record_model_usage(model: str):
    """
    Records a successful request for this model.
    Increments daily count and tracks minute timestamp.
    """
    current_pt_date = get_pacific_date_str()
    now_ts = time.time()
    cutoff_ts = now_ts - 60.0

    with _lock:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT pt_date, day_count, minute_timestamps FROM model_quotas WHERE model_name = ?", (model,))
        row = cursor.fetchone()

        if not row:
            timestamps = [now_ts]
            cursor.execute("""
            INSERT INTO model_quotas (model_name, pt_date, day_count, minute_timestamps, is_daily_blocked)
            VALUES (?, ?, 1, ?, 0)
            """, (model, current_pt_date, json.dumps(timestamps)))
        else:
            pt_date = row["pt_date"]
            if pt_date != current_pt_date:
                day_count = 1
                timestamps = [now_ts]
            else:
                day_count = row["day_count"] + 1
                try:
                    old_ts = json.loads(row["minute_timestamps"] or "[]")
                    timestamps = [ts for ts in old_ts if ts > cutoff_ts]
                except Exception:
                    timestamps = []
                timestamps.append(now_ts)

            cursor.execute("""
            UPDATE model_quotas
            SET pt_date = ?, day_count = ?, minute_timestamps = ?, last_used_at = CURRENT_TIMESTAMP
            WHERE model_name = ?
            """, (current_pt_date, day_count, json.dumps(timestamps), model))

        conn.commit()
        conn.close()


def record_model_rate_limited(model: str, error_text: str):
    """
    Called when Google returns 429 or RESOURCE_EXHAUSTED.
    Locally marks the model as exhausted so we don't spam Google with further failed calls.
    """
    current_pt_date = get_pacific_date_str()
    error_lower = error_text.lower()

    # Determine if it's a daily exhaustion or per-minute rate limit
    is_daily = any(k in error_lower for k in ["daily", "per day", "quota exceeded", "resource_exhausted"])

    with _lock:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT model_name FROM model_quotas WHERE model_name = ?", (model,))
        if not cursor.fetchone():
            cursor.execute("""
            INSERT INTO model_quotas (model_name, pt_date, day_count, minute_timestamps, is_daily_blocked)
            VALUES (?, ?, ?, '[]', ?)
            """, (model, current_pt_date, 500 if is_daily else 1, 1 if is_daily else 0))
        else:
            if is_daily:
                cursor.execute("""
                UPDATE model_quotas
                SET is_daily_blocked = 1, pt_date = ?
                WHERE model_name = ?
                """, (current_pt_date, model))
                logger.warning(f"Locally marked {model} as DAILY EXHAUSTED for date {current_pt_date}.")
            else:
                # Fill minute window to cool down for 60 seconds
                now_ts = time.time()
                fake_timestamps = [now_ts] * 30
                cursor.execute("""
                UPDATE model_quotas
                SET minute_timestamps = ?
                WHERE model_name = ?
                """, (json.dumps(fake_timestamps), model))
                logger.warning(f"Locally cooled down {model} for 60s due to per-minute rate limit.")

        conn.commit()
        conn.close()


def get_quota_summary() -> List[Dict[str, Any]]:
    """Returns a full inspection report of all models and their current local quota usage."""
    current_pt_date = get_pacific_date_str()
    now_ts = time.time()
    cutoff_ts = now_ts - 60.0

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT model_name, pt_date, day_count, minute_timestamps, is_daily_blocked FROM model_quotas")
    rows = {r["model_name"]: dict(r) for r in cursor.fetchall()}
    conn.close()

    summary = []
    for cfg in MODEL_CONFIGS:
        m = cfg["model"]
        row = rows.get(m, {})

        pt_date = row.get("pt_date", current_pt_date)
        if pt_date != current_pt_date:
            day_count = 0
            is_blocked = False
            active_rpm = 0
        else:
            day_count = row.get("day_count", 0)
            is_blocked = bool(row.get("is_daily_blocked", 0))
            try:
                raw_ts = json.loads(row.get("minute_timestamps") or "[]")
                active_rpm = len([ts for ts in raw_ts if ts > cutoff_ts])
            except Exception:
                active_rpm = 0

        summary.append({
            "model": m,
            "tier": cfg["tier"],
            "day_used": day_count,
            "day_limit": cfg["rpd"],
            "rpm_active": active_rpm,
            "rpm_limit": cfg["rpm"],
            "is_available": (not is_blocked) and (day_count < cfg["rpd"]) and (active_rpm < cfg["rpm"]),
            "status": "Blocked (Daily)" if is_blocked else ("Exhausted" if day_count >= cfg["rpd"] else ("Cooling (RPM)" if active_rpm >= cfg["rpm"] else "Ready"))
        })

    return summary
