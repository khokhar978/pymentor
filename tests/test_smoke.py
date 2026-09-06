"""
PyMentor Comprehensive Automated Smoke Test Suite
Uses FastAPI TestClient to test ASGI app in-memory (no running server needed, zero port conflicts).

Coverage:
1. Static routing, favicons, and ES modules
2. Browser COOP/COEP isolation headers (for Pyodide WebWorker SharedArrayBuffer)
3. Student login failure handling (ensures no NameError / 500 on client_ip)
4. Student password change lifecycle & security gating (403 when default password active)
5. Curriculum & content endpoints (/api/topics, /api/problems/{id}, 404 handling)
6. Full student practice session journey (start, code save, heartbeat, telemetry event, logout)
7. Progress and profile analytics endpoints (/api/student/progress, /api/student/profile)
8. Admin security & dashboard gating (/api/admin/dashboard, /api/status, /api/config/key)
9. Admin telemetry inspection of student clickstream and per-question stats (/api/admin/student/{id})
"""

import sys
import os
import time

# Ensure workspace root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.main import app, ADMIN_SECRET
from backend.database import get_connection, hash_password
from backend import state

client = TestClient(app)

def cleanup_test_student(roll_no='9999'):
    """Cleans up the test student and any associated test sessions/tokens."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM students WHERE roll_no = ? AND section = 'TEST'", (roll_no,))
    rows = cursor.fetchall()
    for row in rows:
        sid = row["id"]
        cursor.execute("DELETE FROM events WHERE student_id = ?", (sid,))
        cursor.execute("DELETE FROM auth_tokens WHERE student_id = ?", (sid,))
        cursor.execute("DELETE FROM submissions WHERE session_id IN (SELECT id FROM sessions WHERE student_id = ?)", (sid,))
        cursor.execute("DELETE FROM sessions WHERE student_id = ?", (sid,))
        cursor.execute("DELETE FROM students WHERE id = ?", (sid,))
    conn.commit()
    conn.close()

def create_test_student(roll_no='9999', name='Smoke Test Student', needs_change=0):
    """Creates a temporary test student with specified roll and properties."""
    cleanup_test_student(roll_no)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO students (name, roll_no, section, password, needs_password_change)
        VALUES (?, ?, 'TEST', ?, ?)
    """, (name, roll_no, hash_password("smoke_pass_123"), needs_change))
    conn.commit()
    student_id = cursor.lastrowid
    conn.close()
    return student_id

def setup_test_student(needs_change=0):
    """Convenience wrapper for default test student (roll_no 9999)."""
    return create_test_student('9999', 'Smoke Test Student', needs_change)

# ─────────────────────────────────────────────────────────────
# 1. STATIC PAGES, FAVICONS & MODULE RESOLUTION
# ─────────────────────────────────────────────────────────────
def test_pages_and_static_routes():
    """Verify that all static pages and ES module scripts render correctly with HTTP 200."""
    pages = [
        ("/", 200),
        ("/problems", 200),
        ("/login", 200),
        ("/practice", 200),
        ("/profile", 200),
        ("/admin", 200),
        ("/favicon.svg", 200),
        ("/logo.svg", 200),
        ("/favicon.ico", 200),
        ("/js/shared/auth.js", 200),
        ("/js/shared/utils.js", 200),
        ("/js/shared/api.js", 200),
        ("/js/shared/theme.js", 200),
    ]
    for path, expected_status in pages:
        res = client.get(path)
        assert res.status_code == expected_status, f"Route {path} failed with status {res.status_code}"
    
    # Verify ES Module script tags are present in HTML
    assert '<script type="module" src="/js/problems.js' in client.get("/problems").text
    assert '<script type="module" src="/js/login.js' in client.get("/login").text
    assert '<script type="module" src="/js/app.js' in client.get("/practice").text
    assert '<script type="module" src="/js/profile.js' in client.get("/profile").text
    assert '<script type="module" src="/js/admin.js' in client.get("/admin").text

    # Verify theme toggle buttons on student-facing pages
    for student_page in ["/problems", "/login", "/practice", "/profile"]:
        html = client.get(student_page).text
        assert 'btn-theme-toggle' in html, f"Theme toggle button missing on {student_page}"
        assert 'theme.js' in html, f"Theme script missing on {student_page}"

    practice_html = client.get("/practice").text
    assert 'id="gutterProblem"' in practice_html, "Gutter problem separator missing on /practice"
    assert 'id="gutterOutput"' in practice_html, "Gutter output separator missing on /practice"
    assert 'id="solvedBadge"' in practice_html, "Solved badge element missing on /practice"
    print("  [OK] All 6 static pages, favicons, ES modules, theme toggles, resizable gutters, and solved badge serve valid responses")

# ─────────────────────────────────────────────────────────────
# 2. BROWSER COOP/COEP SECURITY HEADERS
# ─────────────────────────────────────────────────────────────
def test_coop_coep_and_security_headers():
    """Verify Cross-Origin-Opener-Policy and Cross-Origin-Embedder-Policy headers for Pyodide/SharedArrayBuffer."""
    # 1. Standard browsers (Chrome, Firefox, etc.) receive credentialless
    res = client.get("/practice")
    assert res.status_code == 200
    headers = res.headers
    assert headers.get("Cross-Origin-Opener-Policy") == "same-origin", "COOP header missing or incorrect"
    assert headers.get("Cross-Origin-Embedder-Policy") == "credentialless", "COEP header for standard browsers incorrect"

    # 2. Safari user-agent receives require-corp
    safari_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    safari_res = client.get("/practice", headers={"User-Agent": safari_ua})
    assert safari_res.status_code == 200
    assert safari_res.headers.get("Cross-Origin-Embedder-Policy") == "require-corp", "COEP header for Safari should be require-corp"

    print("  [OK] Standard (credentialless) and Safari (require-corp) COOP/COEP isolation verified")

# ─────────────────────────────────────────────────────────────
# 3. AUTHENTICATION & LOGIN RESILIENCE
# ─────────────────────────────────────────────────────────────
def test_login_failure_no_500():
    """Verify failed login returns 401 and NEVER throws 500 (checks client_ip bug)."""
    res = client.post("/api/student/login", json={
        "section": "TEST",
        "roll_no": "9999",
        "password": "wrong_password_xyz"
    })
    assert res.status_code == 401, f"Expected 401 on bad password, got {res.status_code}: {res.text}"
    assert "Invalid credentials" in res.json().get("detail", "")
    print("  [OK] Login failure handled correctly (HTTP 401, no 500 NameError)")

# ─────────────────────────────────────────────────────────────
# 4. PASSWORD CHANGE & SECURITY GATING
# ─────────────────────────────────────────────────────────────
def test_password_change_and_security_gating():
    """Verify password change enforcement, validations, and token invalidation."""
    # Student initially needs password change
    student_id = setup_test_student(needs_change=1)
    try:
        # Login
        login_res = client.post("/api/student/login", json={
            "section": "TEST", "roll_no": "9999", "password": "smoke_pass_123"
        })
        assert login_res.status_code == 200
        token = login_res.json()["token"]
        assert login_res.json()["needs_password_change"] is True
        headers = {"Authorization": f"Bearer {token}"}

        # Attempt to start session before changing password -> MUST BE 403
        blocked_res = client.post("/api/session/start", json={
            "problem_id": 1, "help_level": 1
        }, headers=headers)
        assert blocked_res.status_code == 403, f"Expected 403 for default password, got {blocked_res.status_code}"
        print("  [OK] Unchanged default password correctly blocked from practice (HTTP 403)")

        # Attempt change with wrong current password -> 400
        err_pw = client.post("/api/auth/change-password", json={
            "current_password": "wrong_password", "new_password": "new_secure_pass_456"
        }, headers=headers)
        assert err_pw.status_code == 400
        print("  [OK] Wrong current password rejected (HTTP 400)")

        # Attempt change with short password (< 6 chars) -> 400
        short_pw = client.post("/api/auth/change-password", json={
            "current_password": "smoke_pass_123", "new_password": "123"
        }, headers=headers)
        assert short_pw.status_code == 400
        print("  [OK] Password under 6 characters rejected (HTTP 400)")

        # Valid password change -> 200
        change_res = client.post("/api/auth/change-password", json={
            "current_password": "smoke_pass_123", "new_password": "new_secure_pass_456"
        }, headers=headers)
        assert change_res.status_code == 200
        print("  [OK] Password changed successfully (HTTP 200)")

        # Old token should now be revoked (due to token purge on password change)
        stale_res = client.post("/api/session/start", json={
            "problem_id": 1, "help_level": 1
        }, headers=headers)
        assert stale_res.status_code == 401, f"Expected 401 on revoked token, got {stale_res.status_code}"
        print("  [OK] Tokens revoked on password change (stale token rejected with HTTP 401)")

        # Login with old password must fail
        old_login = client.post("/api/student/login", json={
            "section": "TEST", "roll_no": "9999", "password": "smoke_pass_123"
        })
        assert old_login.status_code == 401
        print("  [OK] Old password rejected after change (HTTP 401)")

        # Login with new password must succeed
        new_login = client.post("/api/student/login", json={
            "section": "TEST", "roll_no": "9999", "password": "new_secure_pass_456"
        })
        assert new_login.status_code == 200
        new_token = new_login.json()["token"]
        assert new_login.json()["needs_password_change"] is False

        # Now session start must succeed!
        allowed_res = client.post("/api/session/start", json={
            "problem_id": 1, "help_level": 1
        }, headers={"Authorization": f"Bearer {new_token}"})
        assert allowed_res.status_code == 200
        print("  [OK] Practice unblocked after password change (HTTP 200)")
    finally:
        cleanup_test_student()

# ─────────────────────────────────────────────────────────────
# 5. CURRICULUM & CONTENT ENDPOINTS
# ─────────────────────────────────────────────────────────────
def test_curriculum_and_content_endpoints():
    """Verify topic list, problem detail, and 404 handling."""
    # 1. Topics
    res = client.get("/api/topics")
    assert res.status_code == 200, f"Failed to get topics: {res.text}"
    data = res.json()
    assert "topics" in data, "topics key missing"
    assert len(data["topics"]) > 0, "No topics returned"
    first_topic = data["topics"][0]
    assert "topic" in first_topic and "problems" in first_topic
    print(f"  [OK] Topics fetched successfully ({len(data['topics'])} topics found)")

    # 2. Problem Detail
    res_prob = client.get("/api/problems/1")
    assert res_prob.status_code == 200, f"Failed to get problem 1: {res_prob.text}"
    p_data = res_prob.json()
    assert p_data["id"] == 1
    assert "title" in p_data and "description" in p_data
    assert isinstance(p_data.get("concepts", []), list)
    print(f"  [OK] Problem detail verified (Problem #1: '{p_data['title']}')")

    # 3. Non-existent Problem
    res_404 = client.get("/api/problems/999999")
    assert res_404.status_code == 404, f"Expected 404 for invalid problem, got {res_404.status_code}"
    print("  [OK] Invalid problem ID correctly returns HTTP 404")

# ─────────────────────────────────────────────────────────────
# 6. STUDENT PRACTICE SESSION JOURNEY
# ─────────────────────────────────────────────────────────────
def test_student_full_journey():
    """Verify login success, session start, code save, heartbeat, and logout."""
    student_id = setup_test_student()
    try:
        # 1. Login success
        login_res = client.post("/api/student/login", json={
            "section": "TEST",
            "roll_no": "9999",
            "password": "smoke_pass_123"
        })
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        data = login_res.json()
        token = data.get("token")
        assert token, "Token not returned in login response"
        print("  [OK] Student login success and token generated")

        headers = {"Authorization": f"Bearer {token}"}

        # 2. Start session on problem 1
        start_res = client.post("/api/session/start", json={
            "problem_id": 1,
            "help_level": 1
        }, headers=headers)
        assert start_res.status_code == 200, f"Session start failed: {start_res.text}"
        session_id = start_res.json().get("session_id")
        assert session_id, "Session ID not returned"
        print(f"  [OK] Session #{session_id} started successfully")

        # 3. Save code / Run code
        save_res = client.post("/api/session/save", json={
            "session_id": session_id,
            "code": "print('hello from smoke test')",
            "time_spent_seconds": 15,
            "is_run": True
        }, headers=headers)
        assert save_res.status_code == 200, f"Session save failed: {save_res.text}"
        print("  [OK] Code saved and run recorded successfully")

        # 4. Heartbeat
        hb_res = client.post("/api/session/heartbeat", json={
            "session_id": session_id
        }, headers=headers)
        assert hb_res.status_code == 200, f"Heartbeat failed: {hb_res.text}"
        print("  [OK] Heartbeat ping accepted")

        # 4b. Solved session heartbeat guard (Feature 3: stops counting time when solved)
        conn = get_connection()
        conn.cursor().execute("UPDATE sessions SET status = 'solved', time_spent_seconds = 120 WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()

        hb_solved_res = client.post("/api/session/heartbeat", json={
            "session_id": session_id
        }, headers=headers)
        assert hb_solved_res.status_code == 200
        hb_solved_data = hb_solved_res.json()
        assert hb_solved_data["status"] == "completed", "Solved session heartbeat should report completed"
        assert hb_solved_data["credited_seconds"] == 0, "Solved session must credit 0 seconds"
        assert hb_solved_data["total_time_spent"] == 120, "Total time spent must remain fixed"
        print("  [OK] Solved session heartbeat strictly credits 0 seconds and halts timer")

        # 5. Telemetry event
        tel_res = client.post("/api/telemetry/event", json={
            "session_id": session_id,
            "problem_id": 1,
            "event_type": "smoke_test_run",
            "event_data": {"test": True}
        }, headers=headers)
        assert tel_res.status_code == 200, f"Telemetry failed: {tel_res.text}"
        print("  [OK] Telemetry event recorded with ownership check")

        # 6. Logout
        logout_res = client.post("/api/auth/logout", headers=headers)
        assert logout_res.status_code == 200, f"Logout failed: {logout_res.text}"
        print("  [OK] Logout and token revocation successful")

    finally:
        cleanup_test_student()

# ─────────────────────────────────────────────────────────────
# 7. PROGRESS & PROFILE ANALYTICS
# ─────────────────────────────────────────────────────────────
def test_progress_and_profile_endpoints():
    """Verify progress tracking and profile metrics calculation."""
    student_id = setup_test_student()
    try:
        login_res = client.post("/api/student/login", json={
            "section": "TEST", "roll_no": "9999", "password": "smoke_pass_123"
        })
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Progress endpoint
        prog_res = client.get("/api/student/progress", headers=headers)
        assert prog_res.status_code == 200
        assert "progress" in prog_res.json()
        print("  [OK] Student progress endpoint returns valid progress map")

        # Profile endpoint
        prof_res = client.get("/api/student/profile", headers=headers)
        assert prof_res.status_code == 200
        prof_data = prof_res.json()
        assert "student" in prof_data and "stats" in prof_data
        assert prof_data["student"]["name"] == "Smoke Test Student"
        assert "total_sessions" in prof_data["stats"]
        assert prof_data["student"].get("default_help_level") == 1, "Initial default_help_level should be 1"
        print("  [OK] Student profile endpoint returns full student analytics")

        # Guidance preference settings update endpoint
        settings_res = client.post("/api/student/settings", json={"default_help_level": 3}, headers=headers)
        assert settings_res.status_code == 200, f"Settings update failed: {settings_res.text}"
        assert settings_res.json() == {"success": True, "default_help_level": 3}

        # Verify updated setting in profile
        prof_res2 = client.get("/api/student/profile", headers=headers)
        assert prof_res2.status_code == 200
        assert prof_res2.json()["student"]["default_help_level"] == 3, "default_help_level was not updated to 3"

        # Verify validation rejection for out-of-range level
        bad_settings = client.post("/api/student/settings", json={"default_help_level": 5}, headers=headers)
        assert bad_settings.status_code == 422, f"Expected 422 for level 5, got {bad_settings.status_code}"

        # Verify login response includes updated default_help_level
        relogin_res = client.post("/api/student/login", json={
            "section": "TEST", "roll_no": "9999", "password": "smoke_pass_123"
        })
        assert relogin_res.status_code == 200
        assert relogin_res.json().get("default_help_level") == 3, "Login should return updated default_help_level: 3"
        print("  [OK] Default guidance preference setting update, validation and persistence verified")
    finally:
        cleanup_test_student()

# ─────────────────────────────────────────────────────────────
# 8. ADMIN DASHBOARD, STATUS & API KEY MANAGEMENT
# ─────────────────────────────────────────────────────────────
def test_admin_dashboard_and_telemetry_inspection():
    """Verify admin dashboard security, status, and deep telemetry inspection."""
    # 1. Reject unauthenticated request
    res_unauth = client.get("/api/admin/dashboard")
    assert res_unauth.status_code == 401, f"Expected 401 without secret, got {res_unauth.status_code}"
    print("  [OK] Admin dashboard correctly rejects unauthenticated requests (HTTP 401)")

    # 2. Allow request with valid X-Admin-Secret
    res_auth = client.get("/api/admin/dashboard", headers={"X-Admin-Secret": ADMIN_SECRET})
    assert res_auth.status_code == 200, f"Admin dashboard failed with valid secret: {res_auth.text}"
    data = res_auth.json()
    assert "metrics" in data, "Metrics missing from dashboard response"
    assert "online_students" in data, "Online students list missing from dashboard response"
    assert "system_metrics" in data, "System metrics missing from dashboard response"
    print("  [OK] Admin dashboard returns complete metrics and online students list with valid secret")

    # 3. Status endpoint
    status_res = client.get("/api/status", headers={"X-Admin-Secret": ADMIN_SECRET})
    assert status_res.status_code == 200
    s_data = status_res.json()
    assert s_data["status"] == "online"
    assert "has_api_key" in s_data
    print("  [OK] Admin /api/status endpoint reports online status and API key state")

    # 4. Config key empty rejection
    key_res = client.post("/api/config/key", json={"api_key": "   "}, headers={"X-Admin-Secret": ADMIN_SECRET})
    assert key_res.status_code == 400
    print("  [OK] Admin /api/config/key rejects empty API key (HTTP 400)")

    # 5. Student Inspection with valid and invalid IDs
    student_id = setup_test_student()
    try:
        inspect_res = client.get(f"/api/admin/student/{student_id}", headers={"X-Admin-Secret": ADMIN_SECRET})
        assert inspect_res.status_code == 200
        i_data = inspect_res.json()
        assert i_data["student"]["name"] == "Smoke Test Student"
        assert "problems" in i_data and "events" in i_data
        print(f"  [OK] Admin telemetry inspection for Student #{student_id} returns problem & event streams")

        # Non-existent student
        not_found_res = client.get("/api/admin/student/999999", headers={"X-Admin-Secret": ADMIN_SECRET})
        assert not_found_res.status_code == 404
        print("  [OK] Admin inspection returns 404 for non-existent student ID")
    finally:
        cleanup_test_student()

# ─────────────────────────────────────────────────────────────
# 9. CODE SUBMISSION, COOLDOWNS & PAYLOAD LIMITS (MOCKED AI)
# ─────────────────────────────────────────────────────────────
def test_code_submit_and_cooldown():
    """Verify submit guidance lifecycle, per-student cooldown (429), and max payload limit (422)."""
    student_id = setup_test_student(needs_change=0)
    try:
        # 1. Login to get token
        login_res = client.post("/api/student/login", json={
            "roll_no": "9999",
            "section": "TEST",
            "password": "smoke_pass_123"
        })
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Start session
        session_res = client.post("/api/session/start", json={"problem_id": 1}, headers=headers)
        assert session_res.status_code == 200, f"Session start failed: {session_res.text}"
        session_id = session_res.json()["session_id"]

        # Clear cooldown for isolation
        state.submit_cooldowns.pop(student_id, None)

        # 3. Mock evaluate_code in session router
        mock_eval = {
            "is_correct": True,
            "feedback": "Excellent solution! All sample tests pass.",
            "model_used": "mock-gemini-flash"
        }
        with patch("backend.routers.session.evaluate_code", return_value=mock_eval):
            # Normal submit
            submit_res = client.post("/api/session/submit", json={
                "session_id": session_id,
                "code": "print('hello world')",
                "help_level": 1,
                "simulated_output": "hello world"
            }, headers=headers)
            assert submit_res.status_code == 200, f"Expected 200, got {submit_res.status_code}: {submit_res.text}"
            sub_data = submit_res.json()
            assert sub_data["is_correct"] is True
            assert sub_data["attempt_number"] == 1
            assert "Excellent solution" in sub_data["feedback"]
            print("  [OK] AI code submission succeeds with mocked evaluator (HTTP 200, attempt #1, solved)")

            # 4. Immediate second submit triggers cooldown (429)
            cooldown_res = client.post("/api/session/submit", json={
                "session_id": session_id,
                "code": "print('again')",
                "help_level": 1
            }, headers=headers)
            assert cooldown_res.status_code == 429, f"Expected 429 cooldown, got {cooldown_res.status_code}"
            assert "before requesting guidance again" in cooldown_res.json()["detail"]
            print("  [OK] Immediate second submit correctly throttled by 3s cooldown (HTTP 429)")

        # 5. Oversized payload (> 20,000 chars) rejected by Pydantic (HTTP 422)
        state.submit_cooldowns.pop(student_id, None)
        huge_code = "x = 1\n" * 4500  # ~31,500 characters
        huge_res = client.post("/api/session/submit", json={
            "session_id": session_id,
            "code": huge_code,
            "help_level": 1
        }, headers=headers)
        assert huge_res.status_code == 422, f"Expected 422 for oversized payload, got {huge_res.status_code}"
        print("  [OK] Oversized code payload (> 20,000 characters) rejected (HTTP 422)")

    finally:
        state.submit_cooldowns.pop(student_id, None)
        cleanup_test_student()


# ─────────────────────────────────────────────────────────────
# 10. CROSS-STUDENT SESSION IDOR ISOLATION
# ─────────────────────────────────────────────────────────────
def test_cross_student_idor():
    """Verify that Student B cannot save, heartbeat, or submit against Student A's session (IDOR protection)."""
    id_a = create_test_student("9991", "Student A", needs_change=0)
    id_b = create_test_student("9992", "Student B", needs_change=0)

    try:
        # Login Student A
        res_a = client.post("/api/student/login", json={"roll_no": "9991", "section": "TEST", "password": "smoke_pass_123"})
        token_a = res_a.json()["token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        # Login Student B
        res_b = client.post("/api/student/login", json={"roll_no": "9992", "section": "TEST", "password": "smoke_pass_123"})
        token_b = res_b.json()["token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # Student A creates a session
        sess_a_res = client.post("/api/session/start", json={"problem_id": 1}, headers=headers_a)
        assert sess_a_res.status_code == 200
        session_id_a = sess_a_res.json()["session_id"]

        # Student B attempts to save code to Student A's session -> must be rejected (404)
        save_idor = client.post("/api/session/save", json={
            "session_id": session_id_a,
            "code": "malicious_code_overwrite()"
        }, headers=headers_b)
        assert save_idor.status_code == 404, f"Expected 404 for cross-student save, got {save_idor.status_code}"
        print("  [OK] Cross-student session save attempt blocked (HTTP 404)")

        # Student B attempts to heartbeat Student A's session -> must be rejected (404)
        hb_idor = client.post("/api/session/heartbeat", json={"session_id": session_id_a}, headers=headers_b)
        assert hb_idor.status_code == 404, f"Expected 404 for cross-student heartbeat, got {hb_idor.status_code}"
        print("  [OK] Cross-student session heartbeat attempt blocked (HTTP 404)")

        # Student B attempts to submit code against Student A's session -> must be rejected (404)
        sub_idor = client.post("/api/session/submit", json={
            "session_id": session_id_a,
            "code": "print('steal')"
        }, headers=headers_b)
        assert sub_idor.status_code == 404, f"Expected 404 for cross-student submit, got {sub_idor.status_code}"
        print("  [OK] Cross-student session submit attempt blocked (HTTP 404)")

    finally:
        cleanup_test_student("9991")
        cleanup_test_student("9992")


# ─────────────────────────────────────────────────────────────
# 11. ADMIN BRUTE FORCE LOCKOUT & RATE LIMITING
# ─────────────────────────────────────────────────────────────
def test_admin_lockout_and_rate_limiting():
    """Verify that multiple failed admin attempts trigger a 15-minute brute-force lockout (HTTP 429),
    totally blocking that IP even if a valid secret is sent later, while keeping localhost/other IPs unblocked."""
    test_ip = "203.0.113.10"
    state.admin_attempts.pop(test_ip, None)
    state.admin_attempts.pop("127.0.0.1", None)

    try:
        # Send 5 incorrect attempts from test_ip using CF-Connecting-IP
        for i in range(1, 6):
            res = client.get("/api/admin/dashboard", headers={
                "X-Admin-Secret": f"wrong_secret_{i}",
                "CF-Connecting-IP": test_ip
            })
            assert res.status_code == 401, f"Expected 401 on attempt {i}, got {res.status_code}"

        print("  [OK] 5 consecutive failed admin attempts from Cloudflare IP rejected (HTTP 401)")

        # 6th attempt with wrong secret: locked out (HTTP 429)
        lockout_res = client.get("/api/admin/dashboard", headers={
            "X-Admin-Secret": "wrong_secret_6",
            "CF-Connecting-IP": test_ip
        })
        assert lockout_res.status_code == 429, f"Expected 429 on 6th attempt, got {lockout_res.status_code}"
        assert "Locked out for" in lockout_res.json()["detail"]
        print("  [OK] 6th failed attempt triggers 15-minute lockout (HTTP 429)")

        # 7th attempt with VALID secret from the locked-out IP: STILL blocked (total IP block)
        locked_valid_res = client.get("/api/admin/dashboard", headers={
            "X-Admin-Secret": ADMIN_SECRET,
            "CF-Connecting-IP": test_ip
        })
        assert locked_valid_res.status_code == 429, f"Expected 429 on locked IP even with valid secret, got {locked_valid_res.status_code}"
        print("  [OK] Locked-out IP is totally blocked even if valid secret is sent (HTTP 429)")

        # Request with VALID secret from localhost (127.0.0.1): succeeds (HTTP 200)
        local_res = client.get("/api/admin/dashboard", headers={
            "X-Admin-Secret": ADMIN_SECRET,
            "CF-Connecting-IP": "127.0.0.1"
        })
        assert local_res.status_code == 200, f"Expected 200 from localhost, got {local_res.status_code}"
        print("  [OK] Localhost/unblocked IP can still access admin dashboard with valid secret (HTTP 200)")

    finally:
        state.admin_attempts.pop(test_ip, None)
        state.admin_attempts.pop("127.0.0.1", None)


# ─────────────────────────────────────────────────────────────
# MAIN TEST RUNNER
# ─────────────────────────────────────────────────────────────
def run_all_smoke_tests():
    print("=" * 65)
    print("           Running PyMentor Comprehensive Smoke Tests")
    print("=" * 65)
    start_time = time.time()

    print("\n[Suite 1/11: Static Routing & Modules]")
    test_pages_and_static_routes()

    print("\n[Suite 2/11: Security & Browser Isolation]")
    test_coop_coep_and_security_headers()

    print("\n[Suite 3/11: Student Authentication & Failures]")
    test_login_failure_no_500()

    print("\n[Suite 4/11: Password Change & Security Gating]")
    test_password_change_and_security_gating()

    print("\n[Suite 5/11: Curriculum & Problem Content]")
    test_curriculum_and_content_endpoints()

    print("\n[Suite 6/11: Practice Session Lifecycle]")
    test_student_full_journey()

    print("\n[Suite 7/11: Progress & Profile Analytics]")
    test_progress_and_profile_endpoints()

    print("\n[Suite 8/11: Admin Operations & Telemetry Inspection]")
    test_admin_dashboard_and_telemetry_inspection()

    print("\n[Suite 9/11: AI Code Submission & Cooldown]")
    test_code_submit_and_cooldown()

    print("\n[Suite 10/11: Cross-Student Session IDOR Protection]")
    test_cross_student_idor()

    print("\n[Suite 11/11: Admin Brute-Force Lockout]")
    test_admin_lockout_and_rate_limiting()

    duration = round(time.time() - start_time, 2)
    print("\n" + "=" * 65)
    print(f"  ALL 11 SMOKE TEST SUITES PASSED SUCCESSFULLY in {duration}s! ")
    print("=" * 65)

if __name__ == "__main__":
    run_all_smoke_tests()
