"""
Problem, topic, and curriculum content endpoints.
"""

import json
from fastapi import APIRouter, HTTPException, Depends, Response

try:
    from pymentor.backend.database import get_connection
    from pymentor.backend.deps import get_current_student
except ImportError:
    from backend.database import get_connection
    from backend.deps import get_current_student

router = APIRouter(prefix="/api", tags=["content"])


@router.get("/topics")
def get_topics():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, topic, title, difficulty, concepts
    FROM problems
    ORDER BY id ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    topics_dict = {}
    for r in rows:
        t = r["topic"]
        if t not in topics_dict:
            topics_dict[t] = []
        topics_dict[t].append({
            "id": r["id"],
            "title": r["title"],
            "difficulty": r["difficulty"],
            "concepts": json.loads(r["concepts"]) if r["concepts"] else []
        })

    result = [{"topic": k, "problems": v} for k, v in topics_dict.items()]
    return {"topics": result}


@router.get("/student/progress")
def get_student_progress(response: Response, student_id: int = Depends(get_current_student)):
    """
    Returns per-problem progress status and time spent for the logged-in student.
    Each problem is classified as:
      - 'solved'      : at least one submission with is_correct=1
      - 'attempted'   : has sessions/submissions but no correct submission
      - 'not_started' : no sessions at all
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 
        p_sessions.problem_id,
        p_sessions.time_spent_seconds,
        COALESCE(sub_agg.has_correct, 0) as has_correct,
        COALESCE(sub_agg.submission_count, 0) as submission_count
    FROM (
        SELECT problem_id, SUM(COALESCE(time_spent_seconds, 0)) as time_spent_seconds
        FROM sessions
        WHERE student_id = ?
        GROUP BY problem_id
    ) p_sessions
    LEFT JOIN (
        SELECT s.problem_id, MAX(sub.is_correct) as has_correct, COUNT(sub.id) as submission_count
        FROM sessions s
        JOIN submissions sub ON sub.session_id = s.id
        WHERE s.student_id = ?
        GROUP BY s.problem_id
    ) sub_agg ON p_sessions.problem_id = sub_agg.problem_id
    """, (student_id, student_id))
    rows = cursor.fetchall()
    conn.close()

    progress = {}
    for r in rows:
        pid = r["problem_id"]
        time_spent = r["time_spent_seconds"] or 0
        if r["has_correct"] == 1:
            status = "solved"
        elif r["submission_count"] > 0 or time_spent > 0:
            status = "attempted"
        else:
            status = "not_started"

        progress[pid] = {
            "status": status,
            "time_spent_seconds": time_spent
        }

    return {"progress": progress}


@router.get("/problems/{problem_id}")
def get_problem(problem_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, topic, title, difficulty, description, sample_input, sample_output, concepts, starter_code
    FROM problems
    WHERE id = ?
    """, (problem_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Problem not found")

    return {
        "id": row["id"],
        "topic": row["topic"],
        "title": row["title"],
        "difficulty": row["difficulty"],
        "description": row["description"],
        "sample_input": row["sample_input"],
        "sample_output": row["sample_output"],
        "concepts": json.loads(row["concepts"]) if row["concepts"] else [],
        "starter_code": row["starter_code"] or ""
    }
