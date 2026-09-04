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
    {
        "model": "gemini-3.5-flash-lite",
        "rpd": 500,
        "rpm": 15,
        "tier": "Gemini Flash Lite (Primary)",
        "priority": 1
    },
    {
        "model": "gemini-3.1-flash-lite",
        "rpd": 500,
        "rpm": 15,
        "tier": "Gemini Flash Lite (Secondary)",
        "priority": 2
    },
    {
        "model": "gemini-3.8-flash",
        "rpd": 20,
        "rpm": 5,
        "tier": "Gemini 3.8 Flash (Premium)",
        "priority": 3
    },
    {
        "model": "gemini-3.7-flash",
        "rpd": 20,
        "rpm": 5,
        "tier": "Gemini 3.7 Flash (Premium)",
        "priority": 4
    },
    {
        "model": "gemini-3.6-flash",
        "rpd": 20,
        "rpm": 5,
        "tier": "Gemini 3.6 Flash (Premium)",
        "priority": 5
    },
    {
        "model": "gemini-3.5-flash",
        "rpd": 20,
        "rpm": 5,
        "tier": "Gemini 3.5 Flash (Premium)",
        "priority": 6
    },
    {
        "model": "gemini-2.5-flash",
        "rpd": 20,
        "rpm": 5,
        "tier": "Gemini 2.5 Flash (Standard)",
        "priority": 7
    },
    # ── EMERGENCY SAFETY NET (Used only if all 1,100 Gemini calls are spent) ──
    {
        "model": "gemma-4-31b-it",
        "rpd": 14400,
        "rpm": 30,
        "tier": "Gemma 4 31B (Emergency Fallback 1)",
        "priority": 8
    },
    {
        "model": "gemma-4-26b-a4b-it",
        "rpd": 14400,
        "rpm": 30,
        "tier": "Gemma 4 26B (Emergency Fallback 2)",
        "priority": 9
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


def get_available_models() -> List[str]:
    """
    Returns candidate models in strict priority order that have NOT
    exhausted their daily quota or current minute rate.
    Automatically resets counters if Pacific Time date has changed (new day)
    or if timestamps are older than 60 seconds (PC sleep / wait).
    """
    current_pt_date = get_pacific_date_str()
    now_ts = time.time()
    cutoff_ts = now_ts - 60.0

    with _lock:
        conn = get_connection()
        cursor = conn.cursor()

        # Load current stored states
        cursor.execute("SELECT model_name, pt_date, day_count, minute_timestamps, is_daily_blocked FROM model_quotas")
        rows = {r["model_name"]: dict(r) for r in cursor.fetchall()}

        available = []

        for cfg in MODEL_CONFIGS:
            model = cfg["model"]
            rpd = cfg["rpd"]
            rpm = cfg["rpm"]

            row = rows.get(model)
            if not row:
                # First time seeing this model, fully available
                available.append(model)
                continue

            pt_date = row.get("pt_date")
            day_count = row.get("day_count", 0)
            is_daily_blocked = row.get("is_daily_blocked", 0)

            # Check if a new day has started in Pacific Time
            if pt_date != current_pt_date:
                # Quota reset! Reset day_count and block flags in DB
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
                # Daily quota exhausted, skip without making any network call
                continue

            # Minute rate limit check
            try:
                raw_ts = json.loads(row.get("minute_timestamps") or "[]")
                # Filter out timestamps older than 60 seconds (handles sleep / elapsed time)
                valid_ts = [ts for ts in raw_ts if ts > cutoff_ts]
            except Exception:
                valid_ts = []

            if len(valid_ts) >= rpm:
                # Temporarily rate limited for this minute
                continue

            available.append(model)

        conn.close()

        # Fallback safety: If all models are rate limited, return the Gemma emergency models
        if not available:
            logger.warning("All primary models at quota! Falling back to Gemma emergency models.")
            available = ["gemma-4-31b-it", "gemma-4-26b-a4b-it"]

        return available


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
