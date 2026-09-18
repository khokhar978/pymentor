"""
Streak calculation engine for PyMentor.
Tracks consecutive calendar days with at least 1 verified problem solve (status='solved' / is_correct=1).
"""

from datetime import date, timedelta
from typing import Dict, Any, Optional

try:
    from pymentor.backend.database import get_connection
except ImportError:
    from backend.database import get_connection


def compute_student_streak(student_id: int) -> Dict[str, Any]:
    """
    Calculates current streak, longest streak, and daily solve status for a student.
    
    A streak day requires at least one successful submission (is_correct = 1).
    Current streak stays alive if the student solved a problem either today OR yesterday.
    If today's solve hasn't happened yet, current_streak is still active based on yesterday's solve,
    but solved_today will be False, signaling they should practice today to maintain it!
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT DISTINCT DATE(sub.created_at) as solve_date
    FROM submissions sub
    JOIN sessions s ON sub.session_id = s.id
    WHERE s.student_id = ? AND sub.is_correct = 1
    ORDER BY solve_date DESC
    """, (student_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "solved_today": False,
            "last_solve_date": None,
            "badge_text": "❄️ 0",
            "message": "Start your practice streak by solving your first problem!"
        }

    solve_dates = []
    for r in rows:
        val = r[0] if (isinstance(r, tuple) or isinstance(r, list)) else r["solve_date"]
        solve_dates.append(date.fromisoformat(str(val)))
    today = date.today()
    yesterday = today - timedelta(days=1)

    solved_today = (solve_dates[0] == today)
    last_solve_date = solve_dates[0].isoformat()

    # ── Current Streak Calculation ──
    current_streak = 0
    if solve_dates[0] == today:
        current_streak = 1
        expected_date = today - timedelta(days=1)
        for d in solve_dates[1:]:
            if d == expected_date:
                current_streak += 1
                expected_date -= timedelta(days=1)
            else:
                break
    elif solve_dates[0] == yesterday:
        current_streak = 1
        expected_date = yesterday - timedelta(days=1)
        for d in solve_dates[1:]:
            if d == expected_date:
                current_streak += 1
                expected_date -= timedelta(days=1)
            else:
                break
    else:
        # Last solve was before yesterday -> streak has lapsed to 0
        current_streak = 0

    # ── Longest Streak Calculation ──
    longest_streak = 1
    cur_run = 1
    for i in range(len(solve_dates) - 1):
        if solve_dates[i] - timedelta(days=1) == solve_dates[i + 1]:
            cur_run += 1
            if cur_run > longest_streak:
                longest_streak = cur_run
        else:
            cur_run = 1

    longest_streak = max(longest_streak, current_streak)

    # ── Badge & Messaging ──
    if current_streak > 0:
        badge_text = f"🔥 {current_streak}"
        if solved_today:
            message = f"🔥 {current_streak}-day streak active! Great job solving today."
        else:
            message = f"🔥 {current_streak}-day streak! Solve a problem today to keep your fire burning."
    else:
        badge_text = "❄️ 0"
        message = "No active streak. Solve a problem today to ignite your streak!"

    return {
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "solved_today": solved_today,
        "last_solve_date": last_solve_date,
        "badge_text": badge_text,
        "message": message
    }


def compute_all_students_current_streaks() -> Dict[int, int]:
    """
    Batch-computes current streak for all students (used by Leaderboard cache).
    Returns {student_id: current_streak}.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT s.student_id, DATE(sub.created_at) as solve_date
    FROM submissions sub
    JOIN sessions s ON sub.session_id = s.id
    WHERE sub.is_correct = 1
    GROUP BY s.student_id, solve_date
    ORDER BY s.student_id, solve_date DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    by_student: Dict[int, list] = {}
    for r in rows:
        if isinstance(r, tuple) or isinstance(r, list):
            sid, sdate = r[0], r[1]
        else:
            sid, sdate = r["student_id"], r["solve_date"]
        if sid not in by_student:
            by_student[sid] = []
        by_student[sid].append(date.fromisoformat(str(sdate)))

    today = date.today()
    yesterday = today - timedelta(days=1)

    result = {}
    for sid, dates in by_student.items():
        if not dates:
            result[sid] = 0
            continue

        if dates[0] == today:
            streak = 1
            expected = today - timedelta(days=1)
            for d in dates[1:]:
                if d == expected:
                    streak += 1
                    expected -= timedelta(days=1)
                else:
                    break
            result[sid] = streak
        elif dates[0] == yesterday:
            streak = 1
            expected = yesterday - timedelta(days=1)
            for d in dates[1:]:
                if d == expected:
                    streak += 1
                    expected -= timedelta(days=1)
                else:
                    break
            result[sid] = streak
        else:
            result[sid] = 0

    return result
