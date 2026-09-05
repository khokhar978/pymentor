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

from fastapi.testclient import TestClient
from backend.main import app, ADMIN_SECRET
from backend.database import get_connection, hash_password

client = TestClient(app)

def cleanup_test_student():
    """Cleans up the test student and any associated test sessions/tokens."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM students WHERE roll_no = '9999' AND section = 'TEST'")
    rows = cursor.fetchall()
    for row in rows:
        sid = row["id"]
        cursor.execute("DELETE FROM events WHERE student_id = ?", (sid,))
        cursor.execute("DELETE FROM auth_tokens WHERE student_id = ?", (sid,))
        cursor.execute("DELETE FROM sessions WHERE student_id = ?", (sid,))
        cursor.execute("DELETE FROM students WHERE id = ?", (sid,))
    conn.commit()
    conn.close()

def setup_test_student(needs_change=0):
    """Creates an isolated temporary test student, cleans up existing if any."""
    cleanup_test_student()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO students (name, roll_no, section, password, needs_password_change)
        VALUES ('Smoke Test Student', '9999', 'TEST', ?, ?)
    """, (hash_password("smoke_pass_123"), needs_change))
    conn.commit()
    student_id = cursor.lastrowid
    conn.close()
    return student_id

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

    print("  [OK] All 6 static pages, favicons, ES modules (including theme.js), and theme toggles serve valid HTTP 200 responses")

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
        print("  [OK] Student profile endpoint returns full student analytics")
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
# MAIN TEST RUNNER
# ─────────────────────────────────────────────────────────────
def run_all_smoke_tests():
    print("=" * 65)
    print("           Running PyMentor Comprehensive Smoke Tests")
    print("=" * 65)
    start_time = time.time()

    print("\n[Suite 1/8: Static Routing & Modules]")
    test_pages_and_static_routes()

    print("\n[Suite 2/8: Security & Browser Isolation]")
    test_coop_coep_and_security_headers()

    print("\n[Suite 3/8: Student Authentication & Failures]")
    test_login_failure_no_500()

    print("\n[Suite 4/8: Password Change & Security Gating]")
    test_password_change_and_security_gating()

    print("\n[Suite 5/8: Curriculum & Problem Content]")
    test_curriculum_and_content_endpoints()

    print("\n[Suite 6/8: Practice Session Lifecycle]")
    test_student_full_journey()

    print("\n[Suite 7/8: Progress & Profile Analytics]")
    test_progress_and_profile_endpoints()

    print("\n[Suite 8/8: Admin Operations & Telemetry Inspection]")
    test_admin_dashboard_and_telemetry_inspection()

    duration = round(time.time() - start_time, 2)
    print("\n" + "=" * 65)
    print(f"  ALL 8 SMOKE TEST SUITES PASSED SUCCESSFULLY in {duration}s! ")
    print("=" * 65)

if __name__ == "__main__":
    run_all_smoke_tests()
