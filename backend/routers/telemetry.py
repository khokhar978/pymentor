"""
Student telemetry events and profile performance analytics.
"""

from fastapi import APIRouter, HTTPException, Depends, Response

try:
    from pymentor.backend.database import get_connection, log_event
    from pymentor.backend.deps import get_current_student
    from pymentor.backend.models import TelemetryEventRequest, UpdateSettingsRequest
except ImportError:
    from backend.database import get_connection, log_event
    from backend.deps import get_current_student
    from backend.models import TelemetryEventRequest, UpdateSettingsRequest

router = APIRouter(prefix="/api", tags=["telemetry"])


@router.post("/telemetry/event")
def record_telemetry(req: TelemetryEventRequest, student_id: int = Depends(get_current_student)):
    session_id = req.session_id
    if session_id is not None:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM sessions WHERE id = ? AND student_id = ?", (session_id, student_id))
        valid = cursor.fetchone()
        conn.close()
        if not valid:
            session_id = None

    log_event(
        student_id=student_id,
        session_id=session_id,
        problem_id=req.problem_id,
        event_type=req.event_type,
        event_data=req.event_data
    )
    return {"status": "ok"}


@router.get("/student/profile")
def get_profile(response: Response, student_id: int = Depends(get_current_student)):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, roll_no, section, default_help_level FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()
    if not student:
        conn.close()
        raise HTTPException(status_code=404, detail="Student not found")

    # 1. Overall Stats
    cursor.execute("SELECT COUNT(*) as total_sessions FROM sessions WHERE student_id = ?", (student_id,))
    total_sessions = cursor.fetchone()["total_sessions"]

    cursor.execute(
        "SELECT COUNT(DISTINCT problem_id) as completed_problems FROM sessions WHERE student_id = ? AND status = 'solved'",
        (student_id,)
    )
    completed_problems = cursor.fetchone()["completed_problems"]

    cursor.execute("""
        SELECT COUNT(*) as total_attempts 
        FROM submissions sub 
        JOIN sessions s ON sub.session_id = s.id 
        WHERE s.student_id = ?
    """, (student_id,))
    total_attempts = cursor.fetchone()["total_attempts"]

    # 2. Topic Mastery
    cursor.execute("""
        SELECT p.topic, 
               COUNT(p.id) as total,
               SUM(CASE WHEN s.status = 'solved' THEN 1 ELSE 0 END) as completed
        FROM problems p
        LEFT JOIN sessions s ON p.id = s.problem_id AND s.student_id = ?
        GROUP BY p.topic
        ORDER BY p.topic
    """, (student_id,))
    topic_mastery = [dict(row) for row in cursor.fetchall()]

    for t in topic_mastery:
        if t["completed"] is None:
            t["completed"] = 0

    # 3. Activity History
    cursor.execute("""
        SELECT p.title as problem_title, s.status, s.updated_at, 
               s.status = 'solved' as is_solved,
               (SELECT COUNT(*) FROM submissions sub WHERE sub.session_id = s.id) as attempts_count
        FROM sessions s
        JOIN problems p ON s.problem_id = p.id
        WHERE s.student_id = ?
        ORDER BY s.updated_at DESC
        LIMIT 10
    """, (student_id,))
    activity_history = [dict(row) for row in cursor.fetchall()]

    conn.close()

    student_dict = dict(student)
    student_dict["default_help_level"] = student_dict.get("default_help_level") or 1

    return {
        "student": student_dict,
        "stats": {
            "completed_problems": completed_problems,
            "total_attempts": total_attempts,
            "total_sessions": total_sessions
        },
        "topic_mastery": topic_mastery,
        "activity_history": activity_history
    }


@router.post("/student/settings")
def update_settings(req: UpdateSettingsRequest, student_id: int = Depends(get_current_student)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE students SET default_help_level = ? WHERE id = ?",
        (req.default_help_level, student_id)
    )
    conn.commit()
    conn.close()
    return {"success": True, "default_help_level": req.default_help_level}
