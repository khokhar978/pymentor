"""
Learning Report Router
GET /api/report/{problem_id} — returns a student's compiled learning report for a problem.

State machine:
  pending → return {status: "pending"} (frontend polls, never fires a new request)
  ready   → return {status: "ready", report: <text>}
  failed  → generate synchronously, return result
  None    → generate synchronously, return result (edge case)
"""

import logging
from fastapi import APIRouter, HTTPException, Depends

try:
    from pymentor.backend.deps import require_password_changed
    from pymentor.backend.database import (
        get_connection,
        get_learning_report,
        create_or_reset_learning_report,
        save_learning_report,
        mark_learning_report_failed,
    )
    from pymentor.backend.ai_mentor import generate_learning_report
except ImportError:
    from backend.deps import require_password_changed
    from backend.database import (
        get_connection,
        get_learning_report,
        create_or_reset_learning_report,
        save_learning_report,
        mark_learning_report_failed,
    )
    from backend.ai_mentor import generate_learning_report

logger = logging.getLogger("pymentor")

router = APIRouter(prefix="/api", tags=["reports"])


def _fetch_problem_and_submissions(problem_id: int, student_id: int):
    """Load problem data and all submissions for the student's session on this problem."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT title, topic, difficulty, description, sample_input, sample_output
    FROM problems WHERE id = ?
    """, (problem_id,))
    problem_row = cursor.fetchone()
    if not problem_row:
        conn.close()
        return None, []

    problem = dict(problem_row)

    # Find the most recent session for this student + problem
    cursor.execute("""
    SELECT id FROM sessions
    WHERE student_id = ? AND problem_id = ?
    ORDER BY id DESC LIMIT 1
    """, (student_id, problem_id))
    session_row = cursor.fetchone()
    if not session_row:
        conn.close()
        return problem, []

    session_id = session_row["id"]

    cursor.execute("""
    SELECT code, ai_response, simulated_output, attempt_number
    FROM submissions
    WHERE session_id = ?
    ORDER BY attempt_number ASC
    """, (session_id,))
    submissions = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return problem, submissions


@router.get("/report/{problem_id}")
def get_report(problem_id: int, student_id: int = Depends(require_password_changed)):
    """
    Return the learning report for the given problem for the logged-in student.
    Response shape:
      {status: "pending"}                       -- still generating, frontend should poll
      {status: "ready", report: "<text>"}       -- report available
      {status: "error", detail: "<message>"}    -- generation failed even on sync retry
    """
    row = get_learning_report(student_id, problem_id)

    # CASE 1: Report is ready -- return it immediately
    if row and row["status"] == "ready":
        return {"status": "ready", "report": row["report_text"]}

    # CASE 2: Background thread is still running -- do NOT fire a new request
    if row and row["status"] == "pending":
        return {"status": "pending"}

    # CASE 3: Status is 'failed' or no row at all -- generate synchronously as fallback
    # This should be rare (background thread succeeds in 99% of cases)
    logger.info(
        f"[REPORT] Sync fallback generation for student={student_id} problem={problem_id} "
        f"(status={row['status'] if row else 'none'})"
    )

    problem, submissions = _fetch_problem_and_submissions(problem_id, student_id)

    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found.")

    if len(submissions) < 2:
        raise HTTPException(
            status_code=400,
            detail="Learning reports are only available after solving a problem with at least 2 attempts."
        )

    # Get session_id for the reset call
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM sessions WHERE student_id = ? AND problem_id = ? ORDER BY id DESC LIMIT 1",
            (student_id, problem_id)
        )
        sr = cursor.fetchone()
        conn.close()
        session_id = sr["id"] if sr else 0
    except Exception:
        session_id = 0

    create_or_reset_learning_report(student_id, problem_id, session_id)

    try:
        report_text = generate_learning_report(problem=problem, submissions=submissions)
        save_learning_report(student_id, problem_id, report_text)
        return {"status": "ready", "report": report_text}
    except Exception as e:
        mark_learning_report_failed(student_id, problem_id)
        logger.error(f"[REPORT] Sync generation failed for student={student_id} problem={problem_id}: {e}")
        return {"status": "error", "detail": "Report generation failed. Please try again in a moment."}
