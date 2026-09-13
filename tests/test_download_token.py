"""
Comprehensive Test Suite for Admin Log Download Security & Token Minting
"""

import sys
import os
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi.testclient import TestClient
from backend.main import app, ADMIN_SECRET
from backend import state

client = TestClient(app)

def test_download_token_security():
    print("\n--- Running Log Download Security & Token Minting Tests ---")

    # 1. Verify query parameter ?secret= is REJECTED on admin dashboard
    res_dash_query = client.get(f"/api/admin/dashboard?secret={ADMIN_SECRET}")
    assert res_dash_query.status_code == 401, f"Expected 401, got {res_dash_query.status_code}"
    print("[PASS] GET /api/admin/dashboard?secret=... is rejected (401)")

    # 2. Verify query parameter ?admin_secret= is also REJECTED
    res_dash_query2 = client.get(f"/api/admin/dashboard?admin_secret={ADMIN_SECRET}")
    assert res_dash_query2.status_code == 401, f"Expected 401, got {res_dash_query2.status_code}"
    print("[PASS] GET /api/admin/dashboard?admin_secret=... is rejected (401)")

    # 3. Verify query parameter ?secret= is REJECTED on log download
    res_dl_query = client.get(f"/api/admin/logs/download?secret={ADMIN_SECRET}")
    assert res_dl_query.status_code == 401, f"Expected 401, got {res_dl_query.status_code}"
    print("[PASS] GET /api/admin/logs/download?secret=... is rejected (401)")

    # 4. Verify unauthenticated minting request is REJECTED
    res_mint_unauth = client.post("/api/admin/logs/download-token")
    assert res_mint_unauth.status_code == 401, f"Expected 401, got {res_mint_unauth.status_code}"
    print("[PASS] POST /api/admin/logs/download-token without header is rejected (401)")

    # 5. Verify minting with valid header SUCCEEDS
    res_mint = client.post("/api/admin/logs/download-token", headers={"X-Admin-Secret": ADMIN_SECRET})
    assert res_mint.status_code == 200, f"Expected 200, got {res_mint.status_code}"
    data = res_mint.json()
    assert "token" in data and "expires_in" in data
    token = data["token"]
    assert len(token) > 20
    assert token in state.log_download_tokens
    print(f"[PASS] POST /api/admin/logs/download-token minted token ({token[:8]}...) expiring in {data['expires_in']}s")

    # 6. Verify download with valid single-use token SUCCEEDS
    res_dl = client.get(f"/api/admin/logs/download?token={token}")
    assert res_dl.status_code == 200, f"Expected 200, got {res_dl.status_code}"
    assert "text/plain" in res_dl.headers.get("content-type", "")
    print("[PASS] GET /api/admin/logs/download?token=... successfully downloaded logs (200)")

    # 7. Verify token was burned on first use (single-use replay attack prevention)
    res_dl_replay = client.get(f"/api/admin/logs/download?token={token}")
    assert res_dl_replay.status_code == 401, f"Expected 401 on replay, got {res_dl_replay.status_code}"
    print("[PASS] Replay attempt with same token is rejected (401) - Single-use confirmed")

    # 8. Verify invalid / fabricated token is REJECTED
    res_dl_fake = client.get("/api/admin/logs/download?token=fake_invalid_token_123")
    assert res_dl_fake.status_code == 401, f"Expected 401, got {res_dl_fake.status_code}"
    print("[PASS] Fabricated token is rejected (401)")

    # 9. Verify expired token is REJECTED
    fake_expired_token = "test_expired_token_xyz"
    state.log_download_tokens[fake_expired_token] = time.time() - 10  # expired 10s ago
    res_dl_expired = client.get(f"/api/admin/logs/download?token={fake_expired_token}")
    assert res_dl_expired.status_code == 401, f"Expected 401, got {res_dl_expired.status_code}"
    print("[PASS] Expired token is rejected (401)")

    # 10. Verify direct header authentication still works for scripts / cURL
    res_dl_header = client.get("/api/admin/logs/download", headers={"X-Admin-Secret": ADMIN_SECRET})
    assert res_dl_header.status_code == 200, f"Expected 200, got {res_dl_header.status_code}"
    print("[PASS] GET /api/admin/logs/download with X-Admin-Secret header works (200)")

    print("\n" + "=" * 60)
    print("  ALL 10 LOG DOWNLOAD SECURITY TESTS PASSED PERFECTLY!")
    print("=" * 60)

if __name__ == "__main__":
    test_download_token_security()
