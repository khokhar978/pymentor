"""
Leaderboard router for PyMentor.
Provides cached rankings (overall and per-section) based on:
1. Primary: Solved problem count (status='solved')
2. Secondary (tiebreaker): Lower total active time spent on solved problems
Cached server-side on a 5-minute (300s) TTL interval to protect DB performance.
"""

import time
import threading
import logging
from typing import Optional
from fastapi import APIRouter, Query, Request

try:
    from pymentor.backend.database import get_connection
    from pymentor.backend.streak import compute_all_students_current_streaks
except ImportError:
    from backend.database import get_connection
    from backend.streak import compute_all_students_current_streaks

logger = logging.getLogger("pymentor")

router = APIRouter(prefix="/api", tags=["leaderboard"])

# ── In-Memory Leaderboard Cache ──
_cache_lock = threading.RLock()
_CACHE_TTL = 300  # 5 minutes
_cache = {
    "global": None,
    "sections": {},
    "updated_at": 0.0
}


def get_optional_student(request: Request) -> Optional[int]:
    """Extracts student_id from Bearer token if present and valid, otherwise returns None."""
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    parts = auth.split(" ")
    if len(parts) != 2:
        return None
    token = parts[1]
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT student_id FROM auth_tokens WHERE token = ? AND (expires_at IS NULL OR expires_at > datetime('now', 'localtime'))",
            (token,)
        )
        row = cursor.fetchone()
        conn.close()
        return row["student_id"] if row else None
    except Exception:
        return None


def refresh_leaderboard_cache():
    """Recomputes global and per-section rankings from SQLite database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 
        st.id,
        st.name,
        st.section,
        st.roll_no,
        COUNT(DISTINCT CASE WHEN s.status = 'solved' THEN s.problem_id END) as solved_count,
        COALESCE(SUM(CASE WHEN s.status = 'solved' THEN s.time_spent_seconds ELSE 0 END), 0) as total_time_seconds
    FROM students st
    LEFT JOIN sessions s ON st.id = s.student_id
    WHERE st.is_active = 1
    GROUP BY st.id
    ORDER BY solved_count DESC, total_time_seconds ASC, st.roll_no ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    # Pre-compute current streaks for all students
    streak_map = compute_all_students_current_streaks()

    global_board = []
    section_map = {}

    for idx, r in enumerate(rows):
        entry = {
            "rank": idx + 1,
            "id": r["id"],
            "name": r["name"],
            "section": (r["section"] or "").strip().upper(),
            "roll_no": r["roll_no"],
            "solved_count": int(r["solved_count"] or 0),
            "total_time_seconds": int(r["total_time_seconds"] or 0),
            "streak": streak_map.get(r["id"], 0)
        }
        global_board.append(entry)

        sec = entry["section"]
        if sec not in section_map:
            section_map[sec] = []
        section_map[sec].append(entry)

    # Re-calculate ranks within each section
    section_boards = {}
    for sec, entries in section_map.items():
        sec_ranked = []
        for sec_idx, item in enumerate(entries):
            sec_item = dict(item)
            sec_item["rank"] = sec_idx + 1
            sec_ranked.append(sec_item)
        section_boards[sec] = sec_ranked

    with _cache_lock:
        _cache["global"] = global_board
        _cache["sections"] = section_boards
        _cache["updated_at"] = time.time()

    logger.info(f"[LEADERBOARD] Cache refreshed: {len(global_board)} students ranked across {len(section_boards)} sections.")


def get_cached_leaderboard():
    """Returns cached leaderboard data, refreshing if expired."""
    now = time.time()
    if _cache["global"] is None or (now - _cache["updated_at"] > _CACHE_TTL):
        with _cache_lock:
            # Double-checked locking
            if _cache["global"] is None or (time.time() - _cache["updated_at"] > _CACHE_TTL):
                refresh_leaderboard_cache()
    return _cache


@router.get("/leaderboard")
def get_leaderboard(
    request: Request,
    section: Optional[str] = Query(None, description="Section code (e.g. 'A') or empty for global")
):
    """
    Returns the Top 10 rankings and the requesting student's private rank.
    Can be filtered by section using ?section=X.
    Works for both authenticated students (adds private rank) and visitors.
    """
    cache = get_cached_leaderboard()
    student_id = get_optional_student(request)

    # Determine student's own section if authenticated
    student_section = ""
    if student_id:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT section FROM students WHERE id = ?", (student_id,))
        st_row = cursor.fetchone()
        conn.close()
        if st_row and st_row["section"]:
            student_section = st_row["section"].strip().upper()

    target_sec = section.strip().upper() if section and section.strip().upper() != "ALL" else None

    if target_sec:
        board = cache["sections"].get(target_sec, [])
        scope = target_sec
    else:
        board = cache["global"] or []
        scope = "ALL"

    # Find requesting student's rank within this board (if authenticated)
    my_rank_info = None
    if student_id:
        for item in board:
            if item["id"] == student_id:
                my_rank_info = {
                    "rank": item["rank"],
                    "solved_count": item["solved_count"],
                    "total_time_seconds": item["total_time_seconds"],
                    "streak": item.get("streak", 0),
                    "total_students": len(board),
                    "in_top_10": (item["rank"] <= 10)
                }
                break

    # Format top 10 (or only students who solved >= 1 if desired)
    # We strip private student ID from each top 10 row and flag `is_me`
    top_10 = []
    for item in board[:10]:
        top_10.append({
            "rank": item["rank"],
            "name": item["name"],
            "section": item["section"],
            "roll_no": item["roll_no"],
            "solved_count": item["solved_count"],
            "total_time_seconds": item["total_time_seconds"],
            "streak": item.get("streak", 0),
            "is_me": (item["id"] == student_id) if student_id else False
        })

    return {
        "scope": scope,
        "student_section": student_section,
        "top_10": top_10,
        "my_rank": my_rank_info,
        "total_active_students": len(board),
        "cached_at": cache["updated_at"]
    }
