"""
Admin dashboard, system performance, API key management, and student inspection.
"""

import os
import time
import psutil
from fastapi import APIRouter, HTTPException, Depends

try:
    from pymentor.backend.config import ENV_PATH
    from pymentor.backend.models import SetKeyRequest
    from pymentor.backend.deps import verify_admin
    from pymentor.backend import state
    from pymentor.backend.database import get_connection
    from pymentor.backend.ai_mentor import FALLBACK_MODELS, get_api_key
    from pymentor.backend.quota_manager import get_quota_summary
except ImportError:
    from backend.config import ENV_PATH
    from backend.models import SetKeyRequest
    from backend.deps import verify_admin
    from backend import state
    from backend.database import get_connection
    from backend.ai_mentor import FALLBACK_MODELS, get_api_key
    from backend.quota_manager import get_quota_summary

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/status")
def get_status(admin: bool = Depends(verify_admin)):
    has_key = bool(get_api_key())
    masked_key = ""
    if has_key:
        key = get_api_key()
        masked_key = key[:4] + "..." + key[-4:] if len(key) > 8 else "***"
    return {
        "status": "online",
        "has_api_key": has_key,
        "masked_key": masked_key,
        "fallback_models": FALLBACK_MODELS
    }


@router.post("/config/key")
def set_api_key(req: SetKeyRequest, admin: bool = Depends(verify_admin)):
    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")
    os.environ["GEMINI_API_KEY"] = key
    os.environ["GOOGLE_API_KEY"] = key

    # Safely update .env file without destroying other variables
    env_lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            env_lines = f.readlines()

    key_found = False
    for i, line in enumerate(env_lines):
        if line.startswith("GEMINI_API_KEY="):
            env_lines[i] = f"GEMINI_API_KEY={key}\n"
            key_found = True
            break

    if not key_found:
        if env_lines and not env_lines[-1].endswith("\n"):
            env_lines.append("\n")
        env_lines.append(f"GEMINI_API_KEY={key}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(env_lines)

    masked_key = (key[:4] + "..." + key[-4:]) if len(key) > 8 else "***"
    return {
        "message": "API Key saved successfully!",
        "has_api_key": True,
        "masked_key": masked_key
    }


@router.get("/admin/dashboard")
def get_admin_dashboard(admin: bool = Depends(verify_admin)):
    conn = get_connection()
    cursor = conn.cursor()

    # Students metrics
    cursor.execute("SELECT COUNT(*) as c FROM students")
    total_students = cursor.fetchone()["c"]

    # Submission metrics
    cursor.execute("SELECT COUNT(*) as c FROM submissions")
    total_submissions = cursor.fetchone()["c"]

    cursor.execute("SELECT COUNT(*) as c FROM submissions WHERE is_correct = 1")
    total_solved = cursor.fetchone()["c"]

    # Total runs across all sessions
    cursor.execute("SELECT COALESCE(SUM(run_count), 0) as total_runs FROM sessions")
    total_runs = cursor.fetchone()["total_runs"]

    # Problem Analytics
    cursor.execute("""
        SELECT p.title, COUNT(s.id) as attempts, SUM(s.is_correct) as correct
        FROM submissions s
        JOIN sessions ses ON s.session_id = ses.id
        JOIN problems p ON ses.problem_id = p.id
        GROUP BY p.id
        ORDER BY attempts DESC LIMIT 5
    """)
    toughest_problems = [dict(row) for row in cursor.fetchall()]

    # Guidance Usage
    cursor.execute("""
        SELECT help_level, COUNT(*) as c 
        FROM sessions 
        GROUP BY help_level
        ORDER BY help_level ASC
    """)
    guidance_usage = [dict(row) for row in cursor.fetchall()]

    # Live Feed (Recent submissions)
    cursor.execute("""
        SELECT st.name, p.title, sub.is_correct, sub.created_at, ses.help_level, sub.model_used
        FROM submissions sub
        JOIN sessions ses ON sub.session_id = ses.id
        JOIN students st ON ses.student_id = st.id
        JOIN problems p ON ses.problem_id = p.id
        ORDER BY sub.id DESC LIMIT 15
    """)
    recent_activity = [dict(row) for row in cursor.fetchall()]

    # Student Roster
    cursor.execute("""
        SELECT 
            st.id, st.name, st.roll_no, st.section,
            COUNT(DISTINCT s.problem_id) as problems_attempted,
            COUNT(DISTINCT CASE WHEN s.status = 'solved' THEN s.problem_id END) as problems_solved,
            COALESCE(SUM(s.run_count), 0) as total_runs,
            COALESCE(SUM(s.time_spent_seconds), 0) as total_time_spent,
            (SELECT COUNT(*) FROM submissions sub JOIN sessions ses ON sub.session_id = ses.id WHERE ses.student_id = st.id) as total_submissions,
            MAX(COALESCE(s.updated_at, st.created_at)) as last_active
        FROM students st
        LEFT JOIN sessions s ON st.id = s.student_id
        GROUP BY st.id
        ORDER BY st.section ASC, CAST(st.roll_no AS INTEGER) ASC
    """)
    students_roster = [dict(row) for row in cursor.fetchall()]

    # Real-Time Online Students (active heartbeat within last 120 seconds)
    cursor.execute("""
        SELECT 
            st.id as student_id,
            st.name as student_name,
            st.roll_no,
            st.section,
            p.id as problem_id,
            p.title as problem_title,
            p.topic as problem_topic,
            p.difficulty,
            s.id as session_id,
            s.status,
            s.run_count,
            s.time_spent_seconds,
            s.last_heartbeat_at,
            CAST(MAX(0, ROUND((julianday('now', 'localtime') - julianday(s.last_heartbeat_at)) * 86400)) AS INTEGER) as seconds_ago
        FROM sessions s
        JOIN students st ON s.student_id = st.id
        JOIN problems p ON s.problem_id = p.id
        WHERE s.last_heartbeat_at >= datetime('now', 'localtime', '-120 seconds')
          AND s.id = (
              SELECT s2.id FROM sessions s2
              WHERE s2.student_id = s.student_id
              ORDER BY s2.last_heartbeat_at DESC LIMIT 1
          )
        ORDER BY s.last_heartbeat_at DESC
    """)
    online_students = [dict(row) for row in cursor.fetchall()]
    online_map = {s["student_id"]: s for s in online_students}

    # Annotate students roster with online status and active problem
    for st_row in students_roster:
        sid = st_row["id"]
        if sid in online_map:
            st_row["is_online"] = True
            st_row["current_problem"] = online_map[sid]["problem_title"]
        else:
            st_row["is_online"] = False
            st_row["current_problem"] = None

    conn.close()

    # System Metrics via psutil
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    # Calculate requests per minute (RPM)
    now = time.time()
    rpm = sum(1 for t in state.request_times if now - t <= 60)

    system_metrics = {
        "cpu_percent": cpu_percent,
        "memory_percent": memory.percent,
        "disk_percent": disk.percent,
        "requests_per_minute": rpm
    }

    # Model Quotas
    model_quotas = get_quota_summary()

    # API Key status
    has_key = bool(get_api_key())
    key = get_api_key() if has_key else ""
    masked_key = (key[:4] + "..." + key[-4:]) if len(key) > 8 else ("***" if has_key else "Not Configured")

    return {
        "metrics": {
            "total_students": total_students,
            "total_online": len(online_students),
            "total_submissions": total_submissions,
            "total_solved": total_solved,
            "total_runs": total_runs
        },
        "api_key_status": {
            "has_key": has_key,
            "masked_key": masked_key
        },
        "model_quotas": model_quotas,
        "online_students": online_students,
        "students_roster": students_roster,
        "toughest_problems": toughest_problems,
        "guidance_usage": guidance_usage,
        "recent_activity": recent_activity,
        "system_metrics": system_metrics
    }


@router.get("/admin/student/{student_id}")
def get_admin_student_detail(student_id: int, admin: bool = Depends(verify_admin)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, roll_no, section, created_at FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()
    if not student:
        conn.close()
        raise HTTPException(status_code=404, detail="Student not found")

    # Problems attempted with runs and guidance count
    cursor.execute("""
        SELECT 
            p.id as problem_id, p.title, p.topic, p.difficulty,
            s.id as session_id, s.status, s.help_level, 
            COALESCE(s.run_count, 0) as run_count,
            COALESCE(s.time_spent_seconds, 0) as time_spent_seconds,
            s.updated_at,
            (SELECT COUNT(*) FROM submissions sub WHERE sub.session_id = s.id) as guidance_count,
            (SELECT sub.model_used FROM submissions sub WHERE sub.session_id = s.id ORDER BY sub.id DESC LIMIT 1) as last_model_used
        FROM sessions s
        JOIN problems p ON s.problem_id = p.id
        WHERE s.student_id = ?
        ORDER BY s.updated_at DESC
    """, (student_id,))
    problems = [dict(r) for r in cursor.fetchall()]

    # Recent events
    cursor.execute("""
        SELECT event_type, event_data, created_at
        FROM events
        WHERE student_id = ?
        ORDER BY id DESC LIMIT 20
    """, (student_id,))
    events = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return {
        "student": dict(student),
        "problems": problems,
        "events": events
    }
