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
import gzip
import shutil
import sqlite3
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger("pymentor.github_backup")

try:
    from pymentor.backend.config import ENV_PATH
except ImportError:
    try:
        from backend.config import ENV_PATH
    except ImportError:
        ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ENV_PATH)
except Exception:
    pass

try:
    from pymentor.backend.database import DB_PATH, get_connection
except ImportError:
    from backend.database import DB_PATH, get_connection

def get_github_token() -> str:
    return os.environ.get("GITHUB_BACKUP_TOKEN", "").strip()

def get_github_repo() -> str:
    return os.environ.get("GITHUB_BACKUP_REPO", "").strip()

def get_github_branch() -> str:
    return os.environ.get("GITHUB_BACKUP_BRANCH", "main").strip()

# Optional: Direct peer server URL for instant laptop-to-host sync (leave empty on host PC)
HOST_SERVER_URL = os.environ.get("HOST_SERVER_URL", "").strip()
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "").strip()

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")


def is_github_configured() -> bool:
    """Returns True if GitHub repository and personal access token are configured."""
    return bool(get_github_token() and get_github_repo())


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


def is_candidate_db_newer(candidate_path: str, local_path: str) -> bool:
    """
    Safely compares candidate downloaded database against local database before replacing.
    Prevents overwriting newer local progress (e.g. after an ungraceful restart or crash).
    Returns True if candidate has higher submission max ID/count, or local doesn't exist.
    Returns False if local database already has equal or more recent submissions.
    """
    if not os.path.exists(local_path):
        return True
    loc_conn = None
    cand_conn = None
    try:
        loc_conn = sqlite3.connect(local_path)
        loc_cur = loc_conn.cursor()
        loc_cur.execute("SELECT COALESCE(MAX(id), 0), COUNT(*) FROM submissions")
        loc_sub_max_id, loc_sub_count = loc_cur.fetchone()
        loc_cur.execute("SELECT COALESCE(MAX(id), 0) FROM events")
        loc_evt_max_id = loc_cur.fetchone()[0]
        loc_conn.close()
        loc_conn = None

        cand_conn = sqlite3.connect(candidate_path)
        cand_cur = cand_conn.cursor()
        cand_cur.execute("SELECT COALESCE(MAX(id), 0), COUNT(*) FROM submissions")
        cand_sub_max_id, cand_sub_count = cand_cur.fetchone()
        cand_cur.execute("SELECT COALESCE(MAX(id), 0) FROM events")
        cand_evt_max_id = cand_cur.fetchone()[0]
        cand_conn.close()
        cand_conn = None

        if cand_sub_max_id > loc_sub_max_id or cand_sub_count > loc_sub_count:
            logger.info(
                f"[BACKUP SYNC] Candidate database is newer (Remote subs: {cand_sub_count} [max id {cand_sub_max_id}] "
                f"vs Local subs: {loc_sub_count} [max id {loc_sub_max_id}])."
            )
            return True
        elif cand_sub_max_id == loc_sub_max_id and cand_sub_count == loc_sub_count:
            if cand_evt_max_id > loc_evt_max_id:
                return True
            logger.info(
                f"[BACKUP SYNC] Local database is already up to date with candidate "
                f"(Local subs: {loc_sub_count}, Events: {loc_evt_max_id}). Skipping overwrite."
            )
            return False
        else:
            logger.warning(
                f"[BACKUP SYNC] Local database has MORE RECENT submissions than candidate "
                f"(Local: {loc_sub_count} subs [max id {loc_sub_max_id}] vs Remote: {cand_sub_count} subs [max id {cand_sub_max_id}]). "
                f"Preserving local data to prevent progress loss!"
            )
            return False
    except Exception as e:
        logger.error(f"[BACKUP SYNC] Error comparing database recency: {e}. Preserving local database.")
        return False
    finally:
        if loc_conn:
            try:
                loc_conn.close()
            except Exception:
                pass
        if cand_conn:
            try:
                cand_conn.close()
            except Exception:
                pass


def get_github_file_info(file_path: str = "pymentor_latest.db") -> Optional[Dict[str, Any]]:
    """Fetches commit metadata and file SHA from GitHub repository."""
    if not is_github_configured():
        return None
    token = get_github_token()
    repo = get_github_repo()
    branch = get_github_branch()
    url = f"https://api.github.com/repos/{repo}/contents/{file_path}?ref={branch}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
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
                    # Check if downloaded database is genuinely newer than local copy
                    if is_candidate_db_newer(temp_path, DB_PATH):
                        if os.path.exists(DB_PATH):
                            shutil.copy2(DB_PATH, DB_PATH + ".bak")
                        shutil.move(temp_path, DB_PATH)
                        logger.info("[PEER SYNC] SUCCESS! Restored live database from primary host server.")
                        return True
                    else:
                        logger.info("[PEER SYNC] Local database is already current or newer. Keeping local copy.")
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
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
        # Check pymentor_latest.db.gz first, then pymentor_latest.db
        info = get_github_file_info("pymentor_latest.db.gz")
        is_gz = bool(info and "download_url" in info)
        if not is_gz:
            info = get_github_file_info("pymentor_latest.db")

        if not info or "download_url" not in info:
            logger.info("[GITHUB SYNC] No pymentor_latest.db(.gz) found in GitHub repository. Using local database.")
            return

        download_url = info["download_url"]
        remote_size = info.get("size", 0)
        temp_path = DB_PATH + ".gh_download.tmp"

        local_exists = os.path.exists(DB_PATH)
        local_size = os.path.getsize(DB_PATH) if local_exists else 0

        logger.info(f"[GITHUB SYNC] Downloading backup ({remote_size:,} bytes) from GitHub...")
        token = get_github_token()
        req = urllib.request.Request(download_url, headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "PyMentor-Backup-Agent"
        })
        with urllib.request.urlopen(req, timeout=30) as res:
            downloaded_bytes = res.read()

        # Decompress if gzipped
        if is_gz or downloaded_bytes.startswith(b"\x1f\x8b"):
            try:
                db_bytes = gzip.decompress(downloaded_bytes)
            except Exception as e:
                logger.error(f"[GITHUB SYNC] Gzip decompression failed: {e}")
                return
        else:
            db_bytes = downloaded_bytes

        with open(temp_path, "wb") as f:
            f.write(db_bytes)

        if verify_sqlite_integrity(temp_path):
            if is_candidate_db_newer(temp_path, DB_PATH):
                if local_exists:
                    shutil.copy2(DB_PATH, DB_PATH + ".bak")
                shutil.move(temp_path, DB_PATH)
                logger.info(f"[GITHUB SYNC] SUCCESS! Database restored from GitHub ({len(db_bytes):,} uncompressed bytes).")
            else:
                logger.info("[GITHUB SYNC] Local database is already current or newer than GitHub backup. Keeping local copy.")
        else:
            logger.error("[GITHUB SYNC] Downloaded database failed integrity check. Keeping local copy.")

    except Exception as e:
        logger.error(f"[GITHUB SYNC] Error restoring from GitHub: {e}")
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


_last_backup_fingerprint = None

def get_database_fingerprint() -> str:
    """Returns a string representing the current mutation state of the database."""
    if not os.path.exists(DB_PATH):
        return ""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM submissions")
        sub_count, sub_max_id = cur.fetchone()
        cur.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM events")
        evt_count, evt_max_id = cur.fetchone()
        return f"s:{sub_count}:{sub_max_id}|e:{evt_count}:{evt_max_id}"
    except Exception:
        return ""
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def backup_to_github(only_if_changed: bool = False) -> Dict[str, Any]:
    """
    Creates a fresh local hot-backup and pushes it to private GitHub repository.
    Uses gzip compression for fast, lightweight cloud snapshots.
    If only_if_changed is True, skips push if no new student submissions/events occurred.
    """
    global _last_backup_fingerprint

    current_fingerprint = get_database_fingerprint()
    if only_if_changed and _last_backup_fingerprint and current_fingerprint == _last_backup_fingerprint:
        logger.info("[AUTO BACKUP] No new database activity detected since last backup. Skipping push.")
        return {
            "status": "skipped",
            "reason": "No database changes since last backup",
            "fingerprint": current_fingerprint
        }

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
            token = get_github_token()
            repo = get_github_repo()
            branch = get_github_branch()

            # Read and gzip compress binary database
            with open(local_path, "rb") as f:
                raw_bytes = f.read()
            compressed = gzip.compress(raw_bytes, 9)
            content_b64 = base64.b64encode(compressed).decode("utf-8")
            comp_size = len(compressed)

            # Check existing file SHA on GitHub
            info = get_github_file_info("pymentor_latest.db.gz")
            sha = info.get("sha") if info else None

            url = f"https://api.github.com/repos/{repo}/contents/pymentor_latest.db.gz"
            payload = {
                "message": f"auto-backup: PyMentor database snapshot {timestamp} ({file_size:,} bytes uncompressed, {comp_size:,} bytes compressed)",
                "content": content_b64,
                "branch": branch
            }
            if sha:
                payload["sha"] = sha

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
                "User-Agent": "PyMentor-Backup-Agent"
            }, method="PUT")

            with urllib.request.urlopen(req, timeout=60) as res:
                if res.status in (200, 201):
                    result["github_uploaded"] = True
                    result["github_repo"] = repo
                    result["compressed_size_bytes"] = comp_size
                    _last_backup_fingerprint = current_fingerprint
                    logger.info(f"[GITHUB BACKUP] Uploaded {filename} ({file_size:,} -> {comp_size:,} bytes) to GitHub repo '{repo}'.")
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


def get_github_backups_count() -> int:
    """Counts number of commits on pymentor_latest.db(.gz) in the GitHub repo."""
    if not is_github_configured():
        return 0
    token = get_github_token()
    repo = get_github_repo()
    for fname in ("pymentor_latest.db.gz", "pymentor_latest.db"):
        url = f"https://api.github.com/repos/{repo}/commits?path={fname}&per_page=100"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PyMentor-Backup-Agent"
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                commits = json.loads(res.read())
                if isinstance(commits, list) and len(commits) > 0:
                    return len(commits)
        except Exception:
            pass
    return 0


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

    gh_configured = is_github_configured()
    gh_repo = get_github_repo() if gh_configured else None
    gh_count = get_github_backups_count() if gh_configured else 0

    return {
        "github_configured": gh_configured,
        "github_status": "Connected" if gh_configured else "Not Configured",
        "github_repo": gh_repo,
        "github_backups_count": gh_count,
        "local_backups": local_backups
    }


def save_github_config(token: Optional[str] = None, repo: Optional[str] = None, branch: Optional[str] = "main") -> Dict[str, Any]:
    """
    Validates GitHub credentials against GitHub API, updates in-memory env, and safely persists to .env.
    """
    cur_token = get_github_token()
    cur_repo = get_github_repo()
    cur_branch = get_github_branch()

    new_token = token.strip() if (token and token.strip()) else cur_token
    new_repo = repo.strip() if (repo and repo.strip()) else cur_repo
    new_branch = branch.strip() if (branch and branch.strip()) else (cur_branch or "main")

    if not new_token:
        raise ValueError("GitHub Personal Access Token is required.")
    if not new_repo or "/" not in new_repo:
        raise ValueError("Valid repository in format 'owner/repo' is required.")

    # Test verification against GitHub API
    url = f"https://api.github.com/repos/{new_repo}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {new_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PyMentor-Backup-Agent"
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as res:
            repo_data = json.loads(res.read())
            repo_full_name = repo_data.get("full_name", new_repo)
            is_private = repo_data.get("private", False)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise ValueError("GitHub authentication failed. Token is invalid or expired.")
        elif e.code == 404:
            raise ValueError(f"Repository '{new_repo}' not found, or token lacks 'repo' permissions to access it.")
        else:
            raise ValueError(f"GitHub API returned HTTP {e.code}: {e.reason}")
    except Exception as e:
        raise ValueError(f"Network error contacting GitHub: {e}")

    # Update in-memory environment variables
    os.environ["GITHUB_BACKUP_TOKEN"] = new_token
    os.environ["GITHUB_BACKUP_REPO"] = repo_full_name
    os.environ["GITHUB_BACKUP_BRANCH"] = new_branch

    # Persist to .env safely
    try:
        from pymentor.backend.config import ENV_PATH
    except ImportError:
        from backend.config import ENV_PATH

    env_lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            env_lines = f.readlines()

    updates = {
        "GITHUB_BACKUP_TOKEN": new_token,
        "GITHUB_BACKUP_REPO": repo_full_name,
        "GITHUB_BACKUP_BRANCH": new_branch
    }

    found_keys = set()
    for i, line in enumerate(env_lines):
        line_clean = line.strip()
        for k in updates:
            if line_clean.startswith(f"{k}="):
                env_lines[i] = f"{k}={updates[k]}\n"
                found_keys.add(k)

    for k, v in updates.items():
        if k not in found_keys:
            if env_lines and not env_lines[-1].endswith("\n"):
                env_lines.append("\n")
            env_lines.append(f"{k}={v}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(env_lines)

    masked_token = (new_token[:4] + "..." + new_token[-4:]) if len(new_token) > 8 else "***"
    return {
        "status": "success",
        "message": f"GitHub connected successfully to {repo_full_name} ({'Private' if is_private else 'Public'})!",
        "repo": repo_full_name,
        "branch": new_branch,
        "masked_token": masked_token,
        "is_private": is_private
    }


def get_github_status_summary() -> Dict[str, Any]:
    token = get_github_token()
    repo = get_github_repo()
    branch = get_github_branch()
    masked_token = (token[:4] + "..." + token[-4:]) if len(token) > 8 else ("***" if token else "")
    configured = is_github_configured()
    count = get_github_backups_count() if configured else 0
    return {
        "configured": configured,
        "repo": repo,
        "branch": branch,
        "masked_token": masked_token,
        "backups_count": count
    }
