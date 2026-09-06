"""
Practice session lifecycle: session start/resume, code save/run, heartbeats, and AI evaluation submissions.
"""

import time
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends

try:
    from pymentor.backend.config import SUBMIT_COOLDOWN_SECONDS
    from pymentor.backend import state
    from pymentor.backend.models import (
        SessionStartRequest, SessionSaveRequest, HeartbeatRequest, SubmitCodeRequest
    )
    from pymentor.backend.deps import require_password_changed
    from pymentor.backend.database import get_connection, log_event
    from pymentor.backend.ai_mentor import evaluate_code
except ImportError:
    from backend.config import SUBMIT_COOLDOWN_SECONDS
    from backend import state
    from backend.models import (
        SessionStartRequest, SessionSaveRequest, HeartbeatRequest, SubmitCodeRequest
    )
    from backend.deps import require_password_changed
    from backend.database import get_connection, log_event
    from backend.ai_mentor import evaluate_code

logger = logging.getLogger("pymentor")

router = APIRouter(prefix="/api", tags=["session"])


@router.post("/session/start")
def start_session(req: SessionStartRequest, student_id: int = Depends(require_password_changed)):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, help_level, status
    FROM sessions
    WHERE student_id = ? AND problem_id = ?
    ORDER BY id DESC LIMIT 1
    """, (student_id, req.problem_id))
    session = cursor.fetchone()

    if session:
        session_id = session["id"]
        cursor.execute("""
        UPDATE sessions SET help_level = ?, last_heartbeat_at = datetime('now', 'localtime'), updated_at = datetime('now', 'localtime') WHERE id = ?
        """, (req.help_level, session_id))
        conn.commit()
    else:
        cursor.execute("""
        INSERT INTO sessions (student_id, problem_id, help_level, last_heartbeat_at)
        VALUES (?, ?, ?, datetime('now', 'localtime'))
        """, (student_id, req.problem_id, req.help_level))
        conn.commit()
        session_id = cursor.lastrowid

    cursor.execute("""
    SELECT attempt_number, code, ai_response, is_correct, created_at
    FROM submissions
    WHERE session_id = ?
    ORDER BY attempt_number ASC
    """, (session_id,))
    submissions = [dict(r) for r in cursor.fetchall()]

    # Retrieve last_code and time_spent_seconds from session
    cursor.execute("SELECT last_code, time_spent_seconds FROM sessions WHERE id = ?", (session_id,))
    s_row = cursor.fetchone()
    last_code = s_row["last_code"] if s_row else ""
    time_spent_seconds = (s_row["time_spent_seconds"] or 0) if s_row else 0
    conn.close()

    # Log session start/resume event
    log_event(
        student_id=student_id,
        session_id=session_id,
        problem_id=req.problem_id,
        event_type="session_start",
        event_data={"help_level": req.help_level}
    )
    logger.info(f"[STUDENT SESSION] Started: Student ID={student_id} opened Problem ID={req.problem_id} (Session #{session_id}, Help L{req.help_level})")

    is_solved = any(s["is_correct"] == 1 for s in submissions)

    return {
        "session_id": session_id,
        "help_level": req.help_level,
        "attempts_count": len(submissions),
        "is_solved": is_solved,
        "last_code": last_code,
        "time_spent_seconds": time_spent_seconds,
        "history_count": len(submissions)
    }


@router.post("/session/save")
def save_session(req: SessionSaveRequest, student_id: int = Depends(require_password_changed)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, problem_id FROM sessions WHERE id = ? AND student_id = ?", (req.session_id, student_id))
    session = cursor.fetchone()
    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    updates = ["last_code = ?", "updated_at = datetime('now', 'localtime')"]
    params = [req.code]

    if req.is_run:
        updates.append("run_count = COALESCE(run_count, 0) + 1")

    params.append(req.session_id)

    query = f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(query, tuple(params))
    conn.commit()

    # Log code run event for student telemetry if this was a run action
    if req.is_run:
        log_event(
            student_id=student_id,
            session_id=req.session_id,
            problem_id=session["problem_id"],
            event_type="code_run",
            event_data={"code_len": len(req.code)}
        )
        logger.info(f"[STUDENT RUN] Executed: Student ID={student_id} ran code for Session #{req.session_id} (Problem ID={session['problem_id']}, length: {len(req.code)} chars)")

    conn.close()
    return {"message": "Saved"}


@router.post("/session/heartbeat")
def session_heartbeat(req: HeartbeatRequest, student_id: int = Depends(require_password_changed)):
    """
    Server-authoritative heartbeat.
    Calculates elapsed time strictly using the server's clock.
    Client cannot forge or manipulate time_spent_seconds.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, last_heartbeat_at, time_spent_seconds, status 
    FROM sessions 
    WHERE id = ? AND student_id = ?
    """, (req.session_id, student_id))
    session = cursor.fetchone()
    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    # Stop counting time if the session is already solved
    if session["status"] == "solved":
        conn.close()
        return {
            "status": "completed",
            "credited_seconds": 0,
            "total_time_spent": session["time_spent_seconds"] or 0
        }

    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    last_hb_str = session["last_heartbeat_at"]
    credited_seconds = 0

    if last_hb_str:
        try:
            last_hb_cleaned = last_hb_str.replace("T", " ").split(".")[0]
            last_hb = datetime.strptime(last_hb_cleaned, "%Y-%m-%d %H:%M:%S")
            delta_seconds = int((now - last_hb).total_seconds())

            # Reject heartbeats arriving too fast (< 14s) to stop script spam and avoid unnecessary DB writes
            if delta_seconds < 14:
                conn.close()
                return {
                    "status": "ignored",
                    "credited_seconds": 0,
                    "total_time_spent": session["time_spent_seconds"] or 0
                }

            # Valid heartbeat window (14s to 60s for 20s nominal interval): credit actual elapsed time, capped at 30s
            if 14 <= delta_seconds <= 60:
                credited_seconds = min(delta_seconds, 30)
        except Exception:
            credited_seconds = 0

    if credited_seconds > 0:
        cursor.execute("""
        UPDATE sessions 
        SET time_spent_seconds = COALESCE(time_spent_seconds, 0) + ?,
            last_heartbeat_at = ?,
            updated_at = datetime('now', 'localtime')
        WHERE id = ?
        """, (credited_seconds, now_str, req.session_id))
    else:
        # First heartbeat or after long idle gap (>60s): re-anchor server clock without crediting idle time
        cursor.execute("""
        UPDATE sessions 
        SET last_heartbeat_at = ?,
            updated_at = datetime('now', 'localtime')
        WHERE id = ?
        """, (now_str, req.session_id))

    conn.commit()

    cursor.execute("SELECT time_spent_seconds FROM sessions WHERE id = ?", (req.session_id,))
    total = cursor.fetchone()["time_spent_seconds"] or 0
    conn.close()

    return {
        "status": "ok",
        "credited_seconds": credited_seconds,
        "total_time_spent": total
    }


@router.post("/session/submit")
def submit_code(req: SubmitCodeRequest, student_id: int = Depends(require_password_changed)):
    # Enforce submit cooldown per student to prevent spamming Gemini API
    now = time.time()
    last_submit = state.submit_cooldowns.get(student_id, 0.0)
    if now - last_submit < SUBMIT_COOLDOWN_SECONDS:
        remaining = round(SUBMIT_COOLDOWN_SECONDS - (now - last_submit), 1)
        raise HTTPException(
            status_code=429,
            detail=f"Please wait {remaining}s before requesting guidance again."
        )
    state.submit_cooldowns[student_id] = now

    # Opportunistic pruning of cooldown dictionary
    if len(state.submit_cooldowns) > 1000:
        cutoff = now - 60
        for sid in list(state.submit_cooldowns.keys()):
            if state.submit_cooldowns[sid] < cutoff:
                del state.submit_cooldowns[sid]

    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="Please write your Python code before requesting guidance!")

    # Component 1: Require a real run before guidance is allowed
    # This guarantees the AI always has real terminal output to work with,
    # directly targeting the 49% empty simulated_output stat from the log export.
    if not req.simulated_output or not req.simulated_output.strip():
        raise HTTPException(
            status_code=400,
            detail="Please run your code at least once before requesting guidance. "
                   "The AI mentor needs to see what your code actually does."
        )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT s.id, s.student_id, s.problem_id, s.help_level, s.status,
           st.name as student_name, st.section as student_section, st.roll_no as student_roll
    FROM sessions s
    JOIN students st ON s.student_id = st.id
    WHERE s.id = ? AND s.student_id = ?
    """, (req.session_id, student_id))
    session = cursor.fetchone()

    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found or not authorized")

    problem_id = session["problem_id"]
    help_level = req.help_level or session["help_level"]

    cursor.execute("""
    SELECT title, topic, difficulty, description, sample_input, sample_output, ai_rubric,
           COALESCE(reference_solution, '') as reference_solution
    FROM problems WHERE id = ?
    """, (problem_id,))
    problem = dict(cursor.fetchone())
    problem['id'] = problem_id  # Ensure id is available for logging in ai_mentor

    cursor.execute("""
    SELECT attempt_number, code, ai_response, is_correct
    FROM submissions
    WHERE session_id = ?
    ORDER BY attempt_number ASC
    """, (req.session_id,))
    history = [dict(r) for r in cursor.fetchall()]
    attempt_number = len(history) + 1

    eval_start = time.time()
    eval_result = evaluate_code(
        student_name=session["student_name"],
        section=session["student_section"],
        problem=problem,
        help_level=help_level,
        current_code=code,
        history=history,
        simulated_output=req.simulated_output
    )
    eval_duration_ms = round((time.time() - eval_start) * 1000, 1)

    is_correct = 1 if eval_result["is_correct"] else 0
    feedback = eval_result["feedback"]
    model_used = eval_result.get("model_used", "")

    # Component 7: Don't pollute future prompts with raw infra error strings.
    # If the AI call failed (network/quota), store a neutral placeholder in the DB
    # for future prompt history — the student still sees the friendly retry message.
    store_as_placeholder = eval_result.get("store_as_placeholder", False)
    db_ai_response = eval_result.get("placeholder_text", feedback) if store_as_placeholder else feedback

    cursor.execute("""
    INSERT INTO submissions (session_id, code, ai_response, is_correct, attempt_number, model_used, simulated_output, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
    """, (req.session_id, code, db_ai_response, is_correct, attempt_number, model_used, req.simulated_output or ""))

    if is_correct:
        cursor.execute("UPDATE sessions SET status = 'solved', last_code = ?, updated_at = datetime('now', 'localtime') WHERE id = ?", (code, req.session_id,))
    else:
        cursor.execute("UPDATE sessions SET last_code = ?, updated_at = datetime('now', 'localtime') WHERE id = ?", (code, req.session_id,))

    conn.commit()

    # Get updated total time spent
    cursor.execute("SELECT time_spent_seconds FROM sessions WHERE id = ?", (req.session_id,))
    s_row = cursor.fetchone()
    total_time_spent = (s_row["time_spent_seconds"] or 0) if s_row else 0
    conn.close()

    # Log telemetry event for guidance submission
    log_event(
        student_id=student_id,
        session_id=req.session_id,
        problem_id=problem_id,
        event_type="guidance",
        event_data={
            "attempt_number": attempt_number,
            "is_correct": bool(is_correct),
            "help_level": help_level,
            "model_used": model_used,
            "eval_duration_ms": eval_duration_ms,
            "code_len": len(code),
            "time_spent_seconds": total_time_spent
        }
    )

    result_label = "SOLVED" if is_correct else "IN_PROGRESS"
    logger.info(f"[EVAL] Submit Attempt #{attempt_number}: Student='{session['student_name']}' (Sec {session['student_section']}, Roll {session['student_roll']}) Problem='{problem['title']}' -> Result={result_label} Model='{model_used}' ({eval_duration_ms}ms)")

    return {
        "is_correct": bool(is_correct),
        "feedback": feedback,
        "attempt_number": attempt_number,
        "model_used": model_used,
        "time_spent_seconds": total_time_spent,
        "error": eval_result.get("error")
    }
