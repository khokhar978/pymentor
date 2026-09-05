"""
FastAPI backend for Python Practice platform.
Serves REST API and multi-page frontend.
"""

import os
import json
import logging
import secrets
import time
import psutil
from collections import deque
from datetime import datetime, timedelta
from typing import Optional, List
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Load environment variables
env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(dotenv_path=env_file)
load_dotenv()

try:
    from pymentor.backend.database import get_connection, init_db, verify_password, hash_password, log_event
    from pymentor.backend.ai_mentor import evaluate_code, FALLBACK_MODELS, get_api_key
    from pymentor.backend.quota_manager import get_quota_summary
except ImportError:
    from backend.database import get_connection, init_db, verify_password, hash_password, log_event
    from backend.ai_mentor import evaluate_code, FALLBACK_MODELS, get_api_key
    from backend.quota_manager import get_quota_summary

init_db()

app = FastAPI(title="Python Practice API", version="2.0.0", docs_url=None, redoc_url=None, openapi_url=None)

# Configure CORS - Restrict methods, headers, and origins
raw_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
if raw_origins:
    allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
else:
    allowed_origins = [
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+|.*\.trycloudflare\.com|.*\.ngrok-free\.app|.*\.loca\.lt)(:\d+)?$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Admin-Secret"],
)

# Global request tracker
request_times = deque(maxlen=5000)

@app.middleware("http")
async def track_requests(request: Request, call_next):
    request_times.append(time.time())
    response = await call_next(request)
    return response

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

# Configure basic file logging to logs.txt
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs.txt")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("pymentor")

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "").strip()
if not ADMIN_SECRET or ADMIN_SECRET == "default-admin-secret-change-me":
    logger.critical("CRITICAL: ADMIN_SECRET is not configured or still set to default placeholder in .env. Application refusing to start to prevent unauthenticated admin takeover.")
    raise SystemExit("CRITICAL: ADMIN_SECRET must be set in .env to a non-default secret phrase. Application refusing to start.")

# Rate limiting & cooldown dictionaries
login_attempts = {}    # (roll_no, section) -> (failed_attempts, locked_until)
admin_attempts = {}    # client_ip -> (failed_attempts, locked_until)
submit_cooldowns = {}  # student_id -> last_submit_timestamp
SUBMIT_COOLDOWN_SECONDS = 3.0


# ─────────────────────────────────────────────
# DEPENDENCIES
# ─────────────────────────────────────────────
def get_current_student(request: Request):
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    parts = auth.split(" ")
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Malformed Authorization header")
    token = parts[1]
    
    conn = get_connection()
    cursor = conn.cursor()

    # Opportunistic pruning of expired auth tokens
    if int(time.time()) % 15 == 0:
        try:
            cursor.execute("DELETE FROM auth_tokens WHERE expires_at IS NOT NULL AND expires_at < datetime('now')")
            conn.commit()
        except Exception:
            pass

    cursor.execute(
        "SELECT student_id FROM auth_tokens WHERE token = ? AND (expires_at IS NULL OR expires_at > datetime('now'))",
        (token,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    return row["student_id"]

def require_password_changed(student_id: int = Depends(get_current_student)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT needs_password_change, password FROM students WHERE id = ?", (student_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="Student not found")
    
    needs_change = bool(row["needs_password_change"]) if ("needs_password_change" in row.keys() and row["needs_password_change"] is not None) else verify_password("123", row["password"])
    if needs_change:
        raise HTTPException(
            status_code=403,
            detail="Security notice: Please change your default password in Profile before practicing."
        )
    return student_id

def verify_admin(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Periodic cleanup of expired lockout entries
    if len(admin_attempts) > 50:
        for ip in list(admin_attempts.keys()):
            if admin_attempts[ip][1] <= now:
                del admin_attempts[ip]

    if client_ip in admin_attempts:
        failures, locked_until = admin_attempts[client_ip]
        if now < locked_until:
            wait_seconds = int(locked_until - now)
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed admin attempts. Locked out for {wait_seconds}s."
            )
        elif now >= locked_until and locked_until > 0:
            admin_attempts[client_ip] = (0, 0)

    secret = request.headers.get("X-Admin-Secret", "")
    if not secret or not secrets.compare_digest(secret, ADMIN_SECRET):
        fails = admin_attempts.get(client_ip, (0, 0))[0] + 1
        lock = now + 900 if fails >= 5 else 0  # 15 minutes lockout after 5 failed attempts
        admin_attempts[client_ip] = (fails, lock)
        logger.warning(f"Failed admin authentication attempt from {client_ip} (Attempt {fails}/5)")
        raise HTTPException(status_code=401, detail="Admin unauthorized")

    # Reset failed attempts on success
    if client_ip in admin_attempts:
        del admin_attempts[client_ip]
    return True


# ─────────────────────────────────────────────
# REQUEST MODELS
# ─────────────────────────────────────────────
class LoginRequest(BaseModel):
    section: str
    roll_no: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class SessionStartRequest(BaseModel):
    problem_id: int
    help_level: Optional[int] = 1

class SessionSaveRequest(BaseModel):
    session_id: int
    code: str = Field(..., max_length=20000)
    time_spent_seconds: Optional[int] = None

class SubmitCodeRequest(BaseModel):
    session_id: int
    code: str = Field(..., max_length=20000)
    help_level: Optional[int] = 1
    simulated_output: Optional[str] = Field(None, max_length=10000)

class SetKeyRequest(BaseModel):
    api_key: str

class HeartbeatRequest(BaseModel):
    session_id: int

class TelemetryEventRequest(BaseModel):
    session_id: Optional[int] = None
    problem_id: Optional[int] = None
    event_type: str
    event_data: Optional[dict] = None


# ─────────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/api/status")
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

@app.post("/api/config/key")
def set_api_key(req: SetKeyRequest, admin: bool = Depends(verify_admin)):
    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")
    os.environ["GEMINI_API_KEY"] = key
    os.environ["GOOGLE_API_KEY"] = key
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    
    # Safely update .env file without destroying other variables
    env_lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
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
        
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(env_lines)
        
    masked_key = (key[:4] + "..." + key[-4:]) if len(key) > 8 else "***"
    return {
        "message": "API Key saved successfully!",
        "has_api_key": True,
        "masked_key": masked_key
    }

@app.get("/api/topics")
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

@app.get("/api/student/progress")
def get_student_progress(student_id: int = Depends(get_current_student)):
    """
    Returns per-problem progress status and time spent for the logged-in student.
    Each problem is classified as:
      - 'solved'      : at least one submission with is_correct=1
      - 'attempted'   : has sessions/submissions but no correct submission
      - 'not_started' : no sessions at all
    """
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

@app.get("/api/problems/{problem_id}")
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

@app.post("/api/student/login")
def login_student(req: LoginRequest):
    section = req.section.strip().upper()
    roll_no = req.roll_no.strip()
    password = req.password.strip()
    
    # Rate Limiting Check
    rate_key = (roll_no, section)
    now = time.time()

    # Periodic cleanup of expired lockout entries
    if len(login_attempts) > 100:
        for k in list(login_attempts.keys()):
            if login_attempts[k][1] <= now:
                del login_attempts[k]

    if rate_key in login_attempts:
        failures, locked_until = login_attempts[rate_key]
        if now < locked_until:
            raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")
        elif now >= locked_until and locked_until > 0:
            # Lockout expired
            login_attempts[rate_key] = (0, 0)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, section, roll_no, password, needs_password_change FROM students WHERE roll_no = ? AND section = ?", (roll_no, section))
    student = cursor.fetchone()
    
    if not student or not verify_password(password, student["password"]):
        conn.close()
        # Record failure
        fails = login_attempts.get(rate_key, (0, 0))[0] + 1
        lock = now + 300 if fails >= 5 else 0 # 5 minutes lockout after 5 attempts
        login_attempts[rate_key] = (fails, lock)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Success, reset failures
    if rate_key in login_attempts:
        del login_attempts[rate_key]

    # Generate token with expiry (+7 days)
    token = secrets.token_hex(32)
    expires = (datetime.utcnow() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO auth_tokens (token, student_id, expires_at) VALUES (?, ?, ?)", (token, student["id"], expires))
    conn.commit()
    
    needs_password_change = bool(student["needs_password_change"]) if ("needs_password_change" in student.keys() and student["needs_password_change"] is not None) else verify_password("123", student["password"])
    conn.close()

    log_event(student_id=student["id"], event_type="login", event_data={"section": section, "roll_no": roll_no})

    return {
        "student_id": student["id"],
        "name": student["name"],
        "roll_no": student["roll_no"],
        "section": student["section"],
        "token": token,
        "needs_password_change": needs_password_change
    }

@app.post("/api/auth/logout")
def logout(request: Request):
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        parts = auth.split(" ")
        if len(parts) == 2:
            token = parts[1]
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT student_id FROM auth_tokens WHERE token = ?", (token,))
            row = cursor.fetchone()
            if row:
                log_event(student_id=row["student_id"], event_type="logout")
            conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
            conn.commit()
            conn.close()
    return {"message": "Logged out successfully"}

@app.post("/api/auth/change-password")
def change_password(req: ChangePasswordRequest, student_id: int = Depends(get_current_student)):
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters long")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()
    
    if not verify_password(req.current_password, student["password"]):
        conn.close()
        raise HTTPException(status_code=400, detail="Incorrect current password")
    
    hashed = hash_password(req.new_password)
    cursor.execute("UPDATE students SET password = ?, needs_password_change = 0 WHERE id = ?", (hashed, student_id))
    # Security: Revoke all existing auth tokens for this student so old sessions are terminated immediately
    cursor.execute("DELETE FROM auth_tokens WHERE student_id = ?", (student_id,))
    conn.commit()
    conn.close()

    log_event(student_id=student_id, event_type="password_change")

    return {"message": "Password updated successfully. All sessions revoked. Please log in with your new password."}

@app.post("/api/session/start")
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
        UPDATE sessions SET help_level = ?, last_heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?
        """, (req.help_level, session_id))
        conn.commit()
    else:
        cursor.execute("""
        INSERT INTO sessions (student_id, problem_id, help_level, last_heartbeat_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
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

@app.post("/api/session/save")
def save_session(req: SessionSaveRequest, student_id: int = Depends(require_password_changed)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM sessions WHERE id = ? AND student_id = ?", (req.session_id, student_id))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
        
    if req.time_spent_seconds is not None:
        cursor.execute("""
        UPDATE sessions 
        SET last_code = ?, time_spent_seconds = COALESCE(time_spent_seconds, 0) + ?, updated_at = CURRENT_TIMESTAMP 
        WHERE id = ?
        """, (req.code, req.time_spent_seconds, req.session_id))
    else:
        cursor.execute("UPDATE sessions SET last_code = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (req.code, req.session_id))
    conn.commit()
    conn.close()
    return {"message": "Saved"}

@app.post("/api/session/heartbeat")
def session_heartbeat(req: HeartbeatRequest, student_id: int = Depends(require_password_changed)):
    """
    Server-authoritative heartbeat.
    Calculates elapsed time strictly using the server's clock.
    Client cannot forge or manipulate time_spent_seconds.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, last_heartbeat_at, time_spent_seconds 
    FROM sessions 
    WHERE id = ? AND student_id = ?
    """, (req.session_id, student_id))
    session = cursor.fetchone()
    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    now = datetime.utcnow()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    last_hb_str = session["last_heartbeat_at"]
    credited_seconds = 0

    if last_hb_str:
        try:
            last_hb_cleaned = last_hb_str.replace("T", " ").split(".")[0]
            last_hb = datetime.strptime(last_hb_cleaned, "%Y-%m-%d %H:%M:%S")
            delta_seconds = int((now - last_hb).total_seconds())

            # Reject heartbeats arriving too fast (< 10s) to stop script spam and avoid unnecessary DB writes
            if delta_seconds < 10:
                conn.close()
                return {
                    "status": "ignored",
                    "credited_seconds": 0,
                    "total_time_spent": session["time_spent_seconds"] or 0
                }

            # Valid heartbeat window (10s to 45s): credit actual elapsed time, capped at 25s
            if 10 <= delta_seconds <= 45:
                credited_seconds = min(delta_seconds, 25)
        except Exception:
            credited_seconds = 0

    if credited_seconds > 0:
        cursor.execute("""
        UPDATE sessions 
        SET time_spent_seconds = COALESCE(time_spent_seconds, 0) + ?,
            last_heartbeat_at = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (credited_seconds, now_str, req.session_id))
    else:
        # First heartbeat or after long idle gap (>45s): re-anchor server clock without crediting idle time
        cursor.execute("""
        UPDATE sessions 
        SET last_heartbeat_at = ?,
            updated_at = CURRENT_TIMESTAMP
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

@app.post("/api/session/submit")
def submit_code(req: SubmitCodeRequest, student_id: int = Depends(require_password_changed)):
    # Enforce submit cooldown per student to prevent spamming Gemini API
    now = time.time()
    last_submit = submit_cooldowns.get(student_id, 0.0)
    if now - last_submit < SUBMIT_COOLDOWN_SECONDS:
        remaining = round(SUBMIT_COOLDOWN_SECONDS - (now - last_submit), 1)
        raise HTTPException(
            status_code=429,
            detail=f"Please wait {remaining}s before requesting guidance again."
        )
    submit_cooldowns[student_id] = now

    # Opportunistic pruning of cooldown dictionary
    if len(submit_cooldowns) > 1000:
        cutoff = now - 60
        for sid in list(submit_cooldowns.keys()):
            if submit_cooldowns[sid] < cutoff:
                del submit_cooldowns[sid]

    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="Please write your Python code before requesting guidance!")

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
    SELECT title, topic, difficulty, description, sample_input, sample_output, ai_rubric
    FROM problems WHERE id = ?
    """, (problem_id,))
    problem = dict(cursor.fetchone())

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

    cursor.execute("""
    INSERT INTO submissions (session_id, code, ai_response, is_correct, attempt_number, model_used, simulated_output)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (req.session_id, code, feedback, is_correct, attempt_number, model_used, req.simulated_output or ""))

    if is_correct:
        cursor.execute("UPDATE sessions SET status = 'solved', last_code = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (code, req.session_id,))
    else:
        cursor.execute("UPDATE sessions SET last_code = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (code, req.session_id,))

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

@app.post("/api/telemetry/event")
def record_telemetry(req: TelemetryEventRequest, student_id: int = Depends(get_current_student)):
    log_event(
        student_id=student_id,
        session_id=req.session_id,
        problem_id=req.problem_id,
        event_type=req.event_type,
        event_data=req.event_data
    )
    return {"status": "ok"}

@app.get("/api/student/profile")
def get_profile(student_id: int = Depends(get_current_student)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, roll_no, section FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()
    if not student:
        conn.close()
        raise HTTPException(status_code=404, detail="Student not found")

    # 1. Overall Stats
    cursor.execute("SELECT COUNT(*) as total_sessions FROM sessions WHERE student_id = ?", (student_id,))
    total_sessions = cursor.fetchone()["total_sessions"]

    cursor.execute("SELECT COUNT(DISTINCT problem_id) as completed_problems FROM sessions WHERE student_id = ? AND status = 'solved'", (student_id,))
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
    
    # Fill in None completions with 0
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

    return {
        "student": dict(student),
        "stats": {
            "completed_problems": completed_problems,
            "total_attempts": total_attempts,
            "total_sessions": total_sessions
        },
        "topic_mastery": topic_mastery,
        "activity_history": activity_history
    }

@app.get("/api/admin/dashboard")
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

    conn.close()

    # System Metrics via psutil
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # Calculate requests per minute (RPM)
    now = time.time()
    rpm = sum(1 for t in request_times if now - t <= 60)

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
            "total_submissions": total_submissions,
            "total_solved": total_solved,
            "total_runs": total_runs
        },
        "api_key_status": {
            "has_key": has_key,
            "masked_key": masked_key
        },
        "model_quotas": model_quotas,
        "students_roster": students_roster,
        "toughest_problems": toughest_problems,
        "guidance_usage": guidance_usage,
        "recent_activity": recent_activity,
        "system_metrics": system_metrics
    }

@app.get("/api/admin/student/{student_id}")
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


# ─────────────────────────────────────────────
# STATIC FILE SERVING
# ─────────────────────────────────────────────

if os.path.exists(FRONTEND_DIR):
    css_dir = os.path.join(FRONTEND_DIR, "css")
    js_dir = os.path.join(FRONTEND_DIR, "js")
    if os.path.exists(css_dir):
        app.mount("/css", StaticFiles(directory=css_dir), name="css")
    if os.path.exists(js_dir):
        app.mount("/js", StaticFiles(directory=js_dir), name="js")


@app.get("/favicon.ico")
def serve_favicon_ico():
    """Serve standard favicon.ico file."""
    ico_file = os.path.join(FRONTEND_DIR, "favicon.ico")
    if os.path.exists(ico_file):
        return FileResponse(ico_file, media_type="image/x-icon")
    raise HTTPException(status_code=404, detail="Favicon not found")

@app.get("/favicon.svg")
def serve_favicon_svg():
    """Serve scalable vector favicon.svg file."""
    svg_file = os.path.join(FRONTEND_DIR, "favicon.svg")
    if os.path.exists(svg_file):
        return FileResponse(svg_file, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="Favicon not found")

@app.get("/")
def serve_root():
    """Redirect root to /problems."""
    return RedirectResponse(url="/problems")


@app.get("/problems")
def serve_problems():
    """Serve the problems browser page."""
    problems_file = os.path.join(FRONTEND_DIR, "problems.html")
    if os.path.exists(problems_file):
        return FileResponse(problems_file)
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Python Practice API is running. Frontend not found."}


@app.get("/login")
def serve_login():
    """Serve the login page."""
    login_file = os.path.join(FRONTEND_DIR, "login.html")
    if os.path.exists(login_file):
        return FileResponse(login_file)
    raise HTTPException(status_code=404, detail="Login page not found")


@app.get("/practice")
def serve_practice():
    """Serve the code practice page."""
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Practice page not found")
    
@app.get("/profile")
def serve_profile():
    """Serve the profile dashboard."""
    profile_file = os.path.join(FRONTEND_DIR, "profile.html")
    if os.path.exists(profile_file):
        return FileResponse(profile_file)
    return {"message": "Profile page not found."}

@app.get("/admin")
def serve_admin():
    """Serve the admin dashboard."""
    admin_file = os.path.join(FRONTEND_DIR, "admin.html")
    if os.path.exists(admin_file):
        return FileResponse(admin_file)
    return {"message": "Admin page not found."}
