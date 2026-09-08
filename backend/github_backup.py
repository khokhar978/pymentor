"""
GitHub Automated Database Backup and Startup Sync for PyMentor.
Ensures the local SQLite database is backed up to a private GitHub repository
and automatically restored on server startup if a newer backup exists.
Uses standard library (urllib) — zero external packages or cards needed.
"""

import os
import time
import json
import base64
import shutil
import sqlite3
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger("pymentor.github_backup")

try:
    from pymentor.backend.database import DB_PATH, get_connection
except ImportError:
    from backend.database import DB_PATH, get_connection

# GitHub Configuration from .env
GITHUB_TOKEN = os.environ.get("GITHUB_BACKUP_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_BACKUP_REPO", "").strip()  # e.g. "khokhar978/pymentor-backups"
GITHUB_BRANCH = os.environ.get("GITHUB_BACKUP_BRANCH", "main").strip()

# Optional: Direct peer server URL for instant laptop-to-host sync
HOST_SERVER_URL = os.environ.get("HOST_SERVER_URL", "https://khokhar.in.net").strip()
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "").strip()

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")


def is_github_configured() -> bool:
    """Returns True if GitHub repository and personal access token are configured."""
    return bool(GITHUB_TOKEN and GITHUB_REPO)


def create_local_hot_backup(backup_dir: str = BACKUP_DIR) -> str:
    """
    Creates a non-blocking, transaction-safe hot backup of pymentor.db.
    Safe to execute while students are actively submitting.
    """
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"pymentor_backup_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)

    src = get_connection()
    dst = sqlite3.connect(backup_path)
    try:
        with dst:
            src.backup(dst, pages=100, sleep=0.01)
    finally:
        dst.close()
        src.close()

    prune_local_backups(backup_dir, max_keep=10)
    return backup_path


def prune_local_backups(backup_dir: str = BACKUP_DIR, max_keep: int = 10):
    """Keep only the latest N local backup files to prevent disk bloating."""
    try:
        files = [
            os.path.join(backup_dir, f) for f in os.listdir(backup_dir)
            if f.startswith("pymentor_backup_") and f.endswith(".db")
        ]
        files.sort(key=os.path.getmtime)
        while len(files) > max_keep:
            oldest = files.pop(0)
            try:
                os.remove(oldest)
            except OSError:
                pass
    except Exception as e:
        logger.warning(f"Error pruning local backups: {e}")


def verify_sqlite_integrity(file_path: str) -> bool:
    """Checks whether an SQLite database file is uncorrupted using PRAGMA integrity_check."""
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return False
    try:
        conn = sqlite3.connect(file_path)
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check")
        res = cur.fetchone()
        conn.close()
        return bool(res and res[0] == "ok")
    except Exception as e:
        logger.error(f"SQLite integrity check failed on {file_path}: {e}")
        return False


def get_github_file_info(file_path: str = "pymentor_latest.db") -> Optional[Dict[str, Any]]:
    """Fetches commit metadata and file SHA from GitHub repository."""
    if not is_github_configured():
        return None
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}?ref={GITHUB_BRANCH}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PyMentor-Backup-Agent"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        logger.error(f"[GITHUB BACKUP] HTTP error fetching file info: {e}")
        return None
    except Exception as e:
        logger.error(f"[GITHUB BACKUP] Network error fetching file info: {e}")
        return None


def sync_from_peer_host() -> bool:
    """
    Attempts to download the latest database directly from the live host (e.g. khokhar.in.net).
    Returns True if successfully restored, False otherwise.
    """
    if not HOST_SERVER_URL or not ADMIN_SECRET:
        return False

    url = f"{HOST_SERVER_URL.rstrip('/')}/api/admin/backup/download"
    req = urllib.request.Request(url, headers={
        "X-Admin-Secret": ADMIN_SECRET,
        "User-Agent": "PyMentor-Failover-Client"
    })
    temp_path = DB_PATH + ".peer_sync.tmp"
    try:
        logger.info(f"[PEER SYNC] Checking host server at {url}...")
        with urllib.request.urlopen(req, timeout=6) as res:
            if res.status == 200:
                with open(temp_path, "wb") as f:
                    shutil.copyfileobj(res, f)

                if verify_sqlite_integrity(temp_path):
                    # Check if downloaded is newer
                    if os.path.exists(DB_PATH):
                        shutil.copy2(DB_PATH, DB_PATH + ".bak")
                    shutil.move(temp_path, DB_PATH)
                    logger.info("[PEER SYNC] SUCCESS! Restored live database from primary host server.")
                    return True
                else:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
    except Exception as e:
        logger.info(f"[PEER SYNC] Host server not reachable or offline ({e}). Checking GitHub backup...")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
    return False


def sync_from_github_on_startup():
    """
    Called upon server startup:
    1. First tries direct sync from live host server (if reachable).
    2. If host is offline, checks private GitHub repository for pymentor_latest.db.
    3. If GitHub has a newer copy, downloads, verifies integrity, and replaces local pymentor.db.
    """
    # Step 1: Try direct peer host download
    if sync_from_peer_host():
        return

    # Step 2: Fall back to GitHub private backup repository
    if not is_github_configured():
        logger.info("[GITHUB SYNC] GitHub backup credentials not configured. Using local database.")
        return

    try:
        info = get_github_file_info("pymentor_latest.db")
        if not info or "download_url" not in info:
            logger.info("[GITHUB SYNC] No pymentor_latest.db found in GitHub repository. Using local database.")
            return

        download_url = info["download_url"]
        remote_size = info.get("size", 0)
        temp_path = DB_PATH + ".gh_download.tmp"

        local_exists = os.path.exists(DB_PATH)
        local_size = os.path.getsize(DB_PATH) if local_exists else 0

        logger.info(f"[GITHUB SYNC] Downloading pymentor_latest.db ({remote_size:,} bytes) from GitHub...")
        req = urllib.request.Request(download_url, headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "User-Agent": "PyMentor-Backup-Agent"
        })
        with urllib.request.urlopen(req, timeout=15) as res:
            with open(temp_path, "wb") as f:
                shutil.copyfileobj(res, f)

        if verify_sqlite_integrity(temp_path):
            if local_exists:
                shutil.copy2(DB_PATH, DB_PATH + ".bak")
            shutil.move(temp_path, DB_PATH)
            logger.info(f"[GITHUB SYNC] SUCCESS! Database restored from GitHub ({remote_size:,} bytes).")
        else:
            logger.error("[GITHUB SYNC] Downloaded database failed integrity check. Keeping local copy.")
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        logger.error(f"[GITHUB SYNC] Error restoring from GitHub: {e}")


def backup_to_github() -> Dict[str, Any]:
    """
    Creates a fresh local hot-backup and pushes it to private GitHub repository.
    """
    local_path = create_local_hot_backup()
    filename = os.path.basename(local_path)
    file_size = os.path.getsize(local_path)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    result = {
        "status": "success",
        "local_file": filename,
        "local_path": local_path,
        "size_bytes": file_size,
        "timestamp": timestamp,
        "github_uploaded": False
    }

    if is_github_configured():
        try:
            # Check existing file SHA on GitHub
            info = get_github_file_info("pymentor_latest.db")
            sha = info.get("sha") if info else None

            # Read and encode binary database
            with open(local_path, "rb") as f:
                content_b64 = base64.b64encode(f.read()).decode("utf-8")

            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/pymentor_latest.db"
            payload = {
                "message": f"auto-backup: PyMentor database snapshot {timestamp} ({file_size:,} bytes)",
                "content": content_b64,
                "branch": GITHUB_BRANCH
            }
            if sha:
                payload["sha"] = sha

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
                "User-Agent": "PyMentor-Backup-Agent"
            }, method="PUT")

            with urllib.request.urlopen(req, timeout=30) as res:
                if res.status in (200, 201):
                    result["github_uploaded"] = True
                    result["github_repo"] = GITHUB_REPO
                    logger.info(f"[GITHUB BACKUP] Uploaded {filename} ({file_size:,} bytes) to GitHub repo '{GITHUB_REPO}'.")
        except Exception as e:
            logger.error(f"[GITHUB BACKUP] Failed uploading to GitHub: {e}")
            result["github_error"] = str(e)
    else:
        result["github_note"] = "GitHub backup token/repo not configured. Backup saved locally only."

    return result


def get_latest_local_backup() -> Optional[str]:
    """Returns file path of the newest local backup, or DB_PATH."""
    if os.path.exists(BACKUP_DIR):
        files = [
            os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR)
            if f.startswith("pymentor_backup_") and f.endswith(".db")
        ]
        if files:
            files.sort(key=os.path.getmtime, reverse=True)
            return files[0]
    return DB_PATH if os.path.exists(DB_PATH) else None


def list_backups() -> Dict[str, Any]:
    """Lists local and remote GitHub backups."""
    local_backups = []
    if os.path.exists(BACKUP_DIR):
        for f in os.listdir(BACKUP_DIR):
            if f.endswith(".db"):
                p = os.path.join(BACKUP_DIR, f)
                local_backups.append({
                    "filename": f,
                    "size_bytes": os.path.getsize(p),
                    "modified": datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")
                })
        local_backups.sort(key=lambda x: x["modified"], reverse=True)

    github_status = "Connected" if is_github_configured() else "Not Configured"
    return {
        "github_configured": is_github_configured(),
        "github_status": github_status,
        "github_repo": GITHUB_REPO if is_github_configured() else None,
        "local_backups": local_backups
    }
