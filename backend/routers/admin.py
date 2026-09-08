"""
Admin dashboard, system performance, API key management, and student inspection.
"""

import os
import time
import json
import psutil
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import FileResponse

try:
    from pymentor.backend.config import ENV_PATH
    from pymentor.backend.models import (
        SetKeyRequest, TeacherInstructionsRequest, SqlQueryRequest,
        CreateProblemRequest, UpdateProblemRequest, ReorderProblemsRequest,
        CreateTopicRequest, RenameTopicRequest,
        CreateStudentRequest, UpdateStudentRequest, ResetPasswordRequest, BulkResetPasswordRequest
    )
    from pymentor.backend.deps import verify_admin
    from pymentor.backend import state
    from pymentor.backend.database import get_connection, hash_password
    from pymentor.backend.ai_mentor import FALLBACK_MODELS, get_api_key
    from pymentor.backend.quota_manager import get_quota_summary
    from pymentor.backend.github_backup import (
        backup_to_github, list_backups, get_latest_local_backup, sync_from_github_on_startup, is_github_configured
    )
except ImportError:
    from backend.config import ENV_PATH
    from backend.models import (
        SetKeyRequest, TeacherInstructionsRequest, SqlQueryRequest,
        CreateProblemRequest, UpdateProblemRequest, ReorderProblemsRequest,
        CreateTopicRequest, RenameTopicRequest,
        CreateStudentRequest, UpdateStudentRequest, ResetPasswordRequest, BulkResetPasswordRequest
    )
    from backend.deps import verify_admin
    from backend import state
    from backend.database import get_connection, hash_password
    from backend.ai_mentor import FALLBACK_MODELS, get_api_key
    from backend.quota_manager import get_quota_summary
    from backend.github_backup import (
        backup_to_github, list_backups, get_latest_local_backup, sync_from_github_on_startup, is_github_configured
    )

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
            st.id, st.name, st.roll_no, st.section, COALESCE(st.email, '') as email,
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

    # System Metrics via psutil (non-blocking)
    cpu_percent = psutil.cpu_percent(interval=None)
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
    cursor.execute("SELECT id, name, roll_no, section, COALESCE(email, '') as email, created_at FROM students WHERE id = ?", (student_id,))
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


# ─────────────────────────────────────────────
# TEACHER PROBLEM INSTRUCTIONS (AI DIRECTIVES)
# ─────────────────────────────────────────────

@router.get("/admin/problems/instructions")
def list_all_problem_instructions(admin: bool = Depends(verify_admin)):
    """List all problems with their current teacher instructions."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, title, topic, difficulty, COALESCE(teacher_instructions, '') as teacher_instructions
        FROM problems
        ORDER BY id ASC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    for r in rows:
        r["has_instructions"] = bool(r["teacher_instructions"].strip())
    return {"problems": rows}


@router.get("/admin/problems/{problem_id}/instructions")
def get_problem_instructions(problem_id: int, admin: bool = Depends(verify_admin)):
    """Get the current teacher instructions for a specific problem."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, title, topic, difficulty, COALESCE(teacher_instructions, '') as teacher_instructions
        FROM problems
        WHERE id = ?
    """, (problem_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Problem {problem_id} not found")
    data = dict(row)
    data["problem_id"] = data["id"]
    data["has_instructions"] = bool(data["teacher_instructions"].strip())
    return data


@router.post("/admin/problems/{problem_id}/instructions")
def update_problem_instructions(
    problem_id: int,
    req: TeacherInstructionsRequest,
    admin: bool = Depends(verify_admin)
):
    """Update or set teacher instructions for a specific problem."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM problems WHERE id = ?", (problem_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Problem {problem_id} not found")

    clean_instructions = req.instructions.strip()
    cursor.execute(
        "UPDATE problems SET teacher_instructions = ? WHERE id = ?",
        (clean_instructions, problem_id)
    )
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "problem_id": problem_id,
        "title": row["title"],
        "teacher_instructions": clean_instructions,
        "is_active": bool(clean_instructions)
    }


@router.delete("/admin/problems/{problem_id}/instructions")
def clear_problem_instructions(problem_id: int, admin: bool = Depends(verify_admin)):
    """Clear/remove teacher instructions for a specific problem (reverts to default AI behavior)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM problems WHERE id = ?", (problem_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Problem {problem_id} not found")

    cursor.execute("UPDATE problems SET teacher_instructions = '' WHERE id = ?", (problem_id,))
    conn.commit()
    conn.close()

    return {
        "status": "cleared",
        "problem_id": problem_id,
        "title": row["title"],
        "teacher_instructions": "",
        "is_active": False
    }


@router.post("/admin/sql")
def execute_sql(req: SqlQueryRequest, admin: bool = Depends(verify_admin)):
    """
    Execute raw SQL queries or maintenance statements on the database.
    Protected by X-Admin-Secret. Returns rows for SELECT/PRAGMA, or affected count for DDL/DML.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        raw_query = req.query.strip()
        params = req.params or []
        cursor.execute(raw_query, params)
        first_word = raw_query.split()[0].upper() if raw_query.split() else ""
        if first_word in ("SELECT", "PRAGMA", "EXPLAIN"):
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return {
                "status": "success",
                "type": "query",
                "query": raw_query,
                "row_count": len(rows),
                "rows": rows
            }
        else:
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return {
                "status": "success",
                "type": "execute",
                "query": raw_query,
                "rows_affected": affected
            }
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"SQL Execution Error: {str(e)}")


# ─────────────────────────────────────────────
# ADMIN GROUP 1: PROBLEM / QUESTION MANAGEMENT
# ─────────────────────────────────────────────

@router.post("/admin/problems")
def create_problem(req: CreateProblemRequest, admin: bool = Depends(verify_admin)):
    """Create a new practice problem."""
    conn = get_connection()
    cursor = conn.cursor()

    # Check for title duplicates
    cursor.execute("SELECT id FROM problems WHERE title = ?", (req.title.strip(),))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail=f"A problem with title '{req.title.strip()}' already exists")

    # Ensure topic exists in topics table
    cursor.execute("SELECT id FROM topics WHERE name = ?", (req.topic.strip(),))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO topics (name) VALUES (?)", (req.topic.strip(),))

    concepts_json = json.dumps(req.concepts or [])
    cursor.execute("""
        INSERT INTO problems (
            topic, title, difficulty, description, sample_input, sample_output,
            concepts, starter_code, ai_rubric, reference_solution, teacher_instructions,
            is_active, order_index
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (
        req.topic.strip(),
        req.title.strip(),
        req.difficulty.strip(),
        req.description.strip(),
        req.sample_input or "",
        req.sample_output.strip(),
        concepts_json,
        req.starter_code or "",
        req.ai_rubric.strip(),
        (req.reference_solution or "").strip(),
        (req.teacher_instructions or "").strip(),
        req.order_index or 0
    ))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "id": new_id,
        "title": req.title.strip(),
        "topic": req.topic.strip(),
        "difficulty": req.difficulty.strip()
    }


@router.get("/admin/problems/{problem_id}/full")
def get_full_problem(problem_id: int, admin: bool = Depends(verify_admin)):
    """Get complete problem details including internal rubric and hidden reference solution."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, topic, title, difficulty, description, sample_input, sample_output,
               concepts, starter_code, ai_rubric,
               COALESCE(reference_solution, '') as reference_solution,
               COALESCE(teacher_instructions, '') as teacher_instructions,
               COALESCE(is_active, 1) as is_active,
               COALESCE(order_index, 0) as order_index
        FROM problems WHERE id = ?
    """, (problem_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Problem {problem_id} not found")

    data = dict(row)
    try:
        data["concepts"] = json.loads(data["concepts"]) if data["concepts"] else []
    except Exception:
        data["concepts"] = []
    data["is_active"] = bool(data["is_active"])
    return data


@router.put("/admin/problems/{problem_id}")
def update_problem(problem_id: int, req: UpdateProblemRequest, admin: bool = Depends(verify_admin)):
    """Update any fields of an existing problem."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM problems WHERE id = ?", (problem_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail=f"Problem {problem_id} not found")

    fields = []
    values = []

    if req.topic is not None:
        fields.append("topic = ?")
        values.append(req.topic.strip())
        cursor.execute("INSERT OR IGNORE INTO topics (name) VALUES (?)", (req.topic.strip(),))
    if req.title is not None:
        fields.append("title = ?")
        values.append(req.title.strip())
    if req.difficulty is not None:
        fields.append("difficulty = ?")
        values.append(req.difficulty.strip())
    if req.description is not None:
        fields.append("description = ?")
        values.append(req.description.strip())
    if req.sample_input is not None:
        fields.append("sample_input = ?")
        values.append(req.sample_input)
    if req.sample_output is not None:
        fields.append("sample_output = ?")
        values.append(req.sample_output.strip())
    if req.concepts is not None:
        fields.append("concepts = ?")
        values.append(json.dumps(req.concepts))
    if req.starter_code is not None:
        fields.append("starter_code = ?")
        values.append(req.starter_code)
    if req.ai_rubric is not None:
        fields.append("ai_rubric = ?")
        values.append(req.ai_rubric.strip())
    if req.reference_solution is not None:
        fields.append("reference_solution = ?")
        values.append(req.reference_solution.strip())
    if req.teacher_instructions is not None:
        fields.append("teacher_instructions = ?")
        values.append(req.teacher_instructions.strip())
    if req.is_active is not None:
        fields.append("is_active = ?")
        values.append(1 if req.is_active else 0)
    if req.order_index is not None:
        fields.append("order_index = ?")
        values.append(req.order_index)

    if not fields:
        conn.close()
        return {"status": "no_changes", "id": problem_id}

    values.append(problem_id)
    sql = f"UPDATE problems SET {', '.join(fields)} WHERE id = ?"
    cursor.execute(sql, values)
    conn.commit()
    conn.close()

    return {"status": "success", "id": problem_id, "updated_fields": [f.split()[0] for f in fields]}


@router.delete("/admin/problems/{problem_id}")
def delete_problem(problem_id: int, hard: bool = Query(False), admin: bool = Depends(verify_admin)):
    """
    Delete or deactivate a problem.
    Default (hard=false): Soft-delete (is_active=0) to preserve student submission history.
    hard=true: Permanently deletes if no student submissions exist.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM problems WHERE id = ?", (problem_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Problem {problem_id} not found")

    if hard:
        cursor.execute("""
            SELECT COUNT(sub.id) as count
            FROM submissions sub
            JOIN sessions ses ON sub.session_id = ses.id
            WHERE ses.problem_id = ?
        """, (problem_id,))
        sub_count = cursor.fetchone()["count"]
        if sub_count > 0:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail=f"Cannot permanently delete problem '{row['title']}' because {sub_count} student submission(s) exist. "
                       "Use soft-delete (default) instead to hide it without corrupting grading history."
            )
        cursor.execute("DELETE FROM problems WHERE id = ?", (problem_id,))
        conn.commit()
        conn.close()
        return {"status": "permanently_deleted", "id": problem_id, "title": row["title"]}
    else:
        cursor.execute("UPDATE problems SET is_active = 0 WHERE id = ?", (problem_id,))
        conn.commit()
        conn.close()
        return {"status": "deactivated", "id": problem_id, "title": row["title"], "is_active": False}


@router.post("/admin/problems/reorder")
def reorder_problems(req: ReorderProblemsRequest, admin: bool = Depends(verify_admin)):
    """Update display order for a list of problems."""
    conn = get_connection()
    cursor = conn.cursor()
    for item in req.items:
        cursor.execute("UPDATE problems SET order_index = ? WHERE id = ?", (item.order_index, item.id))
    conn.commit()
    conn.close()
    return {"status": "success", "reordered_count": len(req.items)}


# ─────────────────────────────────────────────
# ADMIN GROUP 2: TOPIC / MODULE MANAGEMENT
# ─────────────────────────────────────────────

@router.get("/admin/topics")
def list_admin_topics(admin: bool = Depends(verify_admin)):
    """List all topics with live aggregated counts and statistics."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COALESCE(t.id, 0) as topic_id,
            COALESCE(t.name, p.topic) as topic_name,
            COALESCE(t.description, '') as description,
            COALESCE(t.order_index, 0) as order_index,
            COUNT(DISTINCT p.id) as total_problems,
            SUM(CASE WHEN COALESCE(p.is_active, 1) = 1 THEN 1 ELSE 0 END) as active_problems,
            COUNT(DISTINCT ses.id) as total_sessions,
            COUNT(DISTINCT CASE WHEN ses.status = 'solved' THEN ses.id END) as solved_sessions
        FROM problems p
        LEFT JOIN topics t ON t.name = p.topic
        LEFT JOIN sessions ses ON ses.problem_id = p.id
        GROUP BY COALESCE(t.name, p.topic)
        ORDER BY COALESCE(t.order_index, 0) ASC, topic_name ASC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {"topics": rows}


@router.post("/admin/topics")
def create_topic(req: CreateTopicRequest, admin: bool = Depends(verify_admin)):
    """Create a new topic category."""
    conn = get_connection()
    cursor = conn.cursor()
    clean_name = req.name.strip()
    cursor.execute("SELECT id FROM topics WHERE name = ?", (clean_name,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail=f"Topic '{clean_name}' already exists")

    cursor.execute(
        "INSERT INTO topics (name, description, order_index) VALUES (?, ?, ?)",
        (clean_name, req.description or "", req.order_index or 0)
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"status": "success", "id": new_id, "name": clean_name}


@router.put("/admin/topics/{topic_identifier}")
def rename_topic(topic_identifier: str, req: RenameTopicRequest, admin: bool = Depends(verify_admin)):
    """Rename a topic and cascade the name change to all associated problems."""
    conn = get_connection()
    cursor = conn.cursor()

    if topic_identifier.isdigit():
        cursor.execute("SELECT id, name FROM topics WHERE id = ?", (int(topic_identifier),))
    else:
        cursor.execute("SELECT id, name FROM topics WHERE name = ?", (topic_identifier,))
    topic_row = cursor.fetchone()

    old_name = topic_row["name"] if topic_row else topic_identifier
    new_name = req.new_name.strip()

    if topic_row:
        cursor.execute(
            "UPDATE topics SET name = ?, description = COALESCE(?, description) WHERE id = ?",
            (new_name, req.description, topic_row["id"])
        )
    else:
        cursor.execute("INSERT INTO topics (name, description) VALUES (?, ?)", (new_name, req.description or ""))

    cursor.execute("UPDATE problems SET topic = ? WHERE topic = ?", (new_name, old_name))
    problems_updated = cursor.rowcount
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "old_name": old_name,
        "new_name": new_name,
        "problems_updated": problems_updated
    }


# ─────────────────────────────────────────────
# ADMIN GROUP 3: STUDENT ACCOUNT MANAGEMENT
# ─────────────────────────────────────────────

@router.get("/admin/students")
def list_students(
    section: str = Query(None),
    search: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    admin: bool = Depends(verify_admin)
):
    """Search, filter, and paginate student roster with completion statistics."""
    conn = get_connection()
    cursor = conn.cursor()

    filters = ["1=1"]
    params = []

    if section:
        filters.append("s.section = ?")
        params.append(section.strip().upper())

    if search:
        filters.append("(s.roll_no LIKE ? OR s.name LIKE ? OR s.email LIKE ?)")
        term = f"%{search.strip()}%"
        params.extend([term, term, term])

    where_clause = " AND ".join(filters)

    cursor.execute(f"SELECT COUNT(*) as count FROM students s WHERE {where_clause}", params)
    total_count = cursor.fetchone()["count"]

    offset = (page - 1) * page_size
    query_params = list(params) + [page_size, offset]

    cursor.execute(f"""
        SELECT
            s.id, s.roll_no, s.name, s.section, s.email,
            COALESCE(s.needs_password_change, 1) as needs_password_change,
            COALESCE(s.default_help_level, 1) as default_help_level,
            COALESCE(s.is_active, 1) as is_active,
            s.created_at,
            COUNT(DISTINCT CASE WHEN ses.status = 'solved' THEN ses.problem_id END) as problems_solved,
            COALESCE(SUM(ses.time_spent_seconds), 0) as total_time_seconds,
            MAX(ses.updated_at) as last_active_at
        FROM students s
        LEFT JOIN sessions ses ON ses.student_id = s.id
        WHERE {where_clause}
        GROUP BY s.id
        ORDER BY s.section ASC, s.roll_no ASC
        LIMIT ? OFFSET ?
    """, query_params)

    students = [dict(r) for r in cursor.fetchall()]
    conn.close()

    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

    return {
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "students": students
    }


@router.post("/admin/students")
def create_student(req: CreateStudentRequest, admin: bool = Depends(verify_admin)):
    """Manually add an individual student account."""
    conn = get_connection()
    cursor = conn.cursor()

    roll = req.roll_no.strip()
    sec = req.section.strip().upper()

    cursor.execute("SELECT id FROM students WHERE roll_no = ? AND section = ?", (roll, sec))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail=f"Student with Roll No '{roll}' and Section '{sec}' already exists")

    hashed_pw = hash_password(req.password or "123")
    cursor.execute("""
        INSERT INTO students (roll_no, name, section, email, password, needs_password_change, default_help_level, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        roll,
        req.name.strip(),
        sec,
        (req.email or "").strip(),
        hashed_pw,
        1 if req.needs_password_change else 0,
        req.default_help_level or 1
    ))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "id": new_id,
        "roll_no": roll,
        "name": req.name.strip(),
        "section": sec,
        "email": (req.email or "").strip(),
        "needs_password_change": req.needs_password_change
    }


@router.put("/admin/students/{student_id}")
def update_student(student_id: int, req: UpdateStudentRequest, admin: bool = Depends(verify_admin)):
    """Edit student details (name, section, email, help level, active status)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM students WHERE id = ?", (student_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail=f"Student ID {student_id} not found")

    fields = []
    values = []
    if req.name is not None:
        fields.append("name = ?")
        values.append(req.name.strip())
    if req.section is not None:
        fields.append("section = ?")
        values.append(req.section.strip().upper())
    if req.email is not None:
        fields.append("email = ?")
        values.append(req.email.strip())
    if req.default_help_level is not None:
        fields.append("default_help_level = ?")
        values.append(req.default_help_level)
    if req.is_active is not None:
        fields.append("is_active = ?")
        values.append(1 if req.is_active else 0)

    if not fields:
        conn.close()
        return {"status": "no_changes", "id": student_id}

    values.append(student_id)
    cursor.execute(f"UPDATE students SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()

    return {"status": "success", "id": student_id, "updated_fields": [f.split()[0] for f in fields]}


@router.post("/admin/students/{student_id}/reset-password")
def reset_student_password(
    student_id: int,
    req: ResetPasswordRequest = None,
    admin: bool = Depends(verify_admin)
):
    """Reset a forgotten student password and revoke all active auth tokens."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, roll_no, name, section FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()
    if not student:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Student ID {student_id} not found")

    new_pwd = (req.new_password if req and req.new_password else "123").strip()
    req_change = 1 if (req is None or req.require_change) else 0
    hashed = hash_password(new_pwd)

    cursor.execute(
        "UPDATE students SET password = ?, needs_password_change = ? WHERE id = ?",
        (hashed, req_change, student_id)
    )
    cursor.execute("DELETE FROM auth_tokens WHERE student_id = ?", (student_id,))
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "student_id": student_id,
        "roll_no": student["roll_no"],
        "name": student["name"],
        "section": student["section"],
        "message": f"Password reset to '{new_pwd}'. Needs password change: {bool(req_change)}. All active tokens revoked."
    }


@router.post("/admin/students/bulk-reset-passwords")
def bulk_reset_passwords(req: BulkResetPasswordRequest, admin: bool = Depends(verify_admin)):
    """Bulk reset student passwords for an entire section (or all students) back to default."""
    conn = get_connection()
    cursor = conn.cursor()

    default_pwd = (req.default_password or "123").strip()
    hashed = hash_password(default_pwd)

    if req.section:
        sec = req.section.strip().upper()
        cursor.execute("SELECT id FROM students WHERE section = ?", (sec,))
        cursor.execute(
            "UPDATE students SET password = ?, needs_password_change = 1 WHERE section = ?",
            (hashed, sec)
        )
        affected = cursor.rowcount
        cursor.execute("DELETE FROM auth_tokens WHERE student_id IN (SELECT id FROM students WHERE section = ?)", (sec,))
    else:
        cursor.execute("SELECT COUNT(*) as count FROM students")
        affected = cursor.fetchone()["count"]
        cursor.execute("UPDATE students SET password = ?, needs_password_change = 1", (hashed,))
        cursor.execute("DELETE FROM auth_tokens")

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "students_affected": affected,
        "section": req.section.upper() if req.section else "ALL",
        "default_password": default_pwd,
        "message": f"Reset passwords for {affected} student(s) to '{default_pwd}'. All active tokens revoked."
    }


@router.delete("/admin/students/{student_id}")
def delete_student(student_id: int, hard: bool = Query(False), admin: bool = Depends(verify_admin)):
    """
    Deactivate (soft-delete) or permanently delete a student.
    Default (hard=false): Sets is_active=0 and revokes tokens.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, roll_no, name, section FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()
    if not student:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Student ID {student_id} not found")

    if hard:
        cursor.execute("DELETE FROM auth_tokens WHERE student_id = ?", (student_id,))
        cursor.execute("DELETE FROM students WHERE id = ?", (student_id,))
        conn.commit()
        conn.close()
        return {"status": "permanently_deleted", "id": student_id, "roll_no": student["roll_no"]}
    else:
        cursor.execute("UPDATE students SET is_active = 0 WHERE id = ?", (student_id,))
        cursor.execute("DELETE FROM auth_tokens WHERE student_id = ?", (student_id,))
        conn.commit()
        conn.close()
        return {"status": "deactivated", "id": student_id, "roll_no": student["roll_no"], "is_active": False}


# ─────────────────────────────────────────────
# BACKUP & FAILOVER SYNC (GITHUB & LOCAL DOWNLOAD)
# ─────────────────────────────────────────────

@router.post("/admin/backup")
def trigger_backup(admin: bool = Depends(verify_admin)):
    """
    Creates an instant, non-blocking hot backup of pymentor.db.
    Uploads snapshot to private GitHub repository if configured in .env.
    """
    result = backup_to_github()
    return result


@router.get("/admin/backup/download")
def download_backup(admin: bool = Depends(verify_admin)):
    """
    Directly streams the newest SQLite database backup file to the client browser or cURL.
    Allows downloading the live database to a laptop with one click.
    """
    path = get_latest_local_backup()
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No database backup file found")
    filename = os.path.basename(path)
    return FileResponse(
        path=path,
        filename=filename,
        media_type="application/x-sqlite3"
    )


@router.get("/admin/backup/status")
def backup_status(admin: bool = Depends(verify_admin)):
    """Lists local and GitHub backup archives with dates and sizes."""
    return list_backups()


@router.post("/admin/backup/restore-github")
@router.post("/admin/backup/restore")
def force_restore_github(admin: bool = Depends(verify_admin)):
    """Manually pull and restore the latest database from GitHub or peer host."""
    sync_from_github_on_startup()
    return {"status": "success", "message": "Synchronized latest database from GitHub/Host."}

