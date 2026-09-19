"""
Notification, announcement, and student group management router for PyMentor.
Provides endpoints for student notifications polling & read tracking,
as well as admin notification broadcasting and group management.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import datetime

try:
    from pymentor.backend.database import get_connection
    from pymentor.backend.deps import get_current_student, verify_admin
    from pymentor.backend.models import (
        CreateNotificationRequest, UpdateNotificationRequest,
        CreateGroupRequest, UpdateGroupRequest, GroupMembersRequest
    )
except ImportError:
    from backend.database import get_connection
    from backend.deps import get_current_student, verify_admin
    from backend.models import (
        CreateNotificationRequest, UpdateNotificationRequest,
        CreateGroupRequest, UpdateGroupRequest, GroupMembersRequest
    )

router = APIRouter(prefix="/api", tags=["notifications"])


# ─────────────────────────────────────────────────────────────────────────
# STUDENT NOTIFICATION ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────

@router.get("/notifications")
def get_student_notifications(student_id: int = Depends(get_current_student)):
    """
    Fetches active, non-expired notifications applicable to the authenticated student.
    Matches notifications targeted to:
      1. 'all'
      2. 'section:<section>'
      3. 'group:<group_id>' (any group the student belongs to)
      4. 'student:<student_id>'
    Returns notifications with their read status and an overall unread_count.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Fetch student info
    cursor.execute("SELECT id, section, is_active FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()
    if not student or not student["is_active"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Student account inactive or not found")

    student_section = student["section"].strip() if student["section"] else ""

    # 2. Fetch student's groups
    cursor.execute("SELECT group_id FROM group_members WHERE student_id = ?", (student_id,))
    group_ids = [r["group_id"] for r in cursor.fetchall()]

    # 3. Build target filter list
    target_conditions = ["target = 'all'"]
    params = []

    if student_section:
        target_conditions.append("target = ?")
        params.append(f"section:{student_section}")

    target_conditions.append("target = ?")
    params.append(f"student:{student_id}")

    if group_ids:
        placeholders = ",".join(["?"] * len(group_ids))
        target_conditions.append(f"target IN ({','.join(['?'] * len(group_ids))})")
        params.extend([f"group:{gid}" for gid in group_ids])

    where_target = " OR ".join(target_conditions)

    # 4. Query notifications
    query = f"""
    SELECT n.id, n.type, n.title, n.message, n.target, n.priority,
           n.expires_at, n.created_at,
           CASE WHEN nr.read_at IS NOT NULL THEN 1 ELSE 0 END AS is_read,
           nr.read_at
    FROM notifications n
    LEFT JOIN notification_reads nr ON nr.notification_id = n.id AND nr.student_id = ?
    WHERE n.is_active = 1
      AND (n.expires_at IS NULL OR n.expires_at > datetime('now', 'localtime'))
      AND ({where_target})
    ORDER BY
      CASE n.priority
        WHEN 'critical' THEN 1
        WHEN 'high' THEN 2
        WHEN 'normal' THEN 3
        WHEN 'low' THEN 4
        ELSE 5
      END ASC,
      n.created_at DESC
    LIMIT 50
    """

    cursor.execute(query, [student_id] + params)
    rows = cursor.fetchall()
    conn.close()

    notifications = []
    unread_count = 0

    for r in rows:
        is_read = bool(r["is_read"])
        if not is_read:
            unread_count += 1
        notifications.append({
            "id": r["id"],
            "type": r["type"],
            "title": r["title"],
            "message": r["message"],
            "target": r["target"],
            "priority": r["priority"],
            "is_read": is_read,
            "read_at": r["read_at"],
            "expires_at": r["expires_at"],
            "created_at": r["created_at"]
        })

    return {
        "notifications": notifications,
        "unread_count": unread_count
    }


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, student_id: int = Depends(get_current_student)):
    """Marks a notification as read/dismissed for the authenticated student."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR IGNORE INTO notification_reads (notification_id, student_id, read_at)
    VALUES (?, ?, datetime('now', 'localtime'))
    """, (notification_id, student_id))

    conn.commit()
    conn.close()
    return {"success": True, "notification_id": notification_id}


@router.post("/notifications/read-all")
def mark_all_notifications_read(student_id: int = Depends(get_current_student)):
    """Marks all eligible active notifications as read for the authenticated student."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT section FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()
    section = student["section"].strip() if (student and student["section"]) else ""

    cursor.execute("SELECT group_id FROM group_members WHERE student_id = ?", (student_id,))
    group_ids = [r["group_id"] for r in cursor.fetchall()]

    target_conditions = ["target = 'all'", "target = ?"]
    params = [f"student:{student_id}"]

    if section:
        target_conditions.append("target = ?")
        params.append(f"section:{section}")

    if group_ids:
        target_conditions.append(f"target IN ({','.join(['?'] * len(group_ids))})")
        params.extend([f"group:{gid}" for gid in group_ids])

    where_target = " OR ".join(target_conditions)

    query = f"""
    INSERT OR IGNORE INTO notification_reads (notification_id, student_id, read_at)
    SELECT id, ?, datetime('now', 'localtime')
    FROM notifications
    WHERE is_active = 1
      AND (expires_at IS NULL OR expires_at > datetime('now', 'localtime'))
      AND ({where_target})
    """
    cursor.execute(query, [student_id] + params)
    conn.commit()
    conn.close()
    return {"success": True}


# ─────────────────────────────────────────────────────────────────────────
# ADMIN NOTIFICATION ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────

@router.get("/admin/notifications")
def admin_list_notifications(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: bool = Depends(verify_admin)
):
    """Lists all created notifications with aggregated read statistics."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as total FROM notifications")
    total = cursor.fetchone()["total"]

    cursor.execute("""
    SELECT n.*,
           COUNT(nr.student_id) AS read_count
    FROM notifications n
    LEFT JOIN notification_reads nr ON nr.notification_id = n.id
    GROUP BY n.id
    ORDER BY n.created_at DESC
    LIMIT ? OFFSET ?
    """, (limit, offset))

    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        result.append({
            "id": r["id"],
            "type": r["type"],
            "title": r["title"],
            "message": r["message"],
            "target": r["target"],
            "priority": r["priority"],
            "is_active": bool(r["is_active"]),
            "expires_at": r["expires_at"],
            "created_by": r["created_by"],
            "created_at": r["created_at"],
            "read_count": r["read_count"]
        })

    return {"notifications": result, "total": total}


@router.post("/admin/notifications")
def admin_create_notification(req: CreateNotificationRequest, admin: bool = Depends(verify_admin)):
    """Creates a new broadcast announcement, banner alert, or personal note."""
    target = req.target.strip() if req.target else "all"

    # Validate target syntax
    if target != "all" and not (
        target.startswith("section:") or
        target.startswith("group:") or
        target.startswith("student:")
    ):
        raise HTTPException(
            status_code=400,
            detail="Target must be 'all', 'section:<sec>', 'group:<id>', or 'student:<id>'"
        )

    expires = req.expires_at.strip() if req.expires_at else None

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO notifications (type, title, message, target, priority, is_active, expires_at, created_by, created_at)
    VALUES (?, ?, ?, ?, ?, 1, ?, 'admin', datetime('now', 'localtime'))
    """, (req.type, req.title.strip(), req.message.strip(), target, req.priority, expires))

    notification_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {"success": True, "id": notification_id}


@router.put("/admin/notifications/{notification_id}")
def admin_update_notification(
    notification_id: int,
    req: UpdateNotificationRequest,
    admin: bool = Depends(verify_admin)
):
    """Updates an existing notification's details or toggle its active status."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM notifications WHERE id = ?", (notification_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Notification not found")

    updates = []
    params = []

    if req.title is not None:
        updates.append("title = ?")
        params.append(req.title.strip())
    if req.message is not None:
        updates.append("message = ?")
        params.append(req.message.strip())
    if req.target is not None:
        updates.append("target = ?")
        params.append(req.target.strip())
    if req.priority is not None:
        updates.append("priority = ?")
        params.append(req.priority.strip())
    if req.is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if req.is_active else 0)
    if req.expires_at is not None:
        updates.append("expires_at = ?")
        params.append(req.expires_at.strip() if req.expires_at else None)

    if updates:
        params.append(notification_id)
        cursor.execute(f"UPDATE notifications SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

    conn.close()
    return {"success": True, "id": notification_id}


@router.delete("/admin/notifications/{notification_id}")
def admin_delete_notification(notification_id: int, admin: bool = Depends(verify_admin)):
    """Permanently deletes a notification and its associated read logs."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM notification_reads WHERE notification_id = ?", (notification_id,))
    cursor.execute("DELETE FROM notifications WHERE id = ?", (notification_id,))
    conn.commit()
    conn.close()

    return {"success": True, "id": notification_id}


@router.get("/admin/notifications/{notification_id}/stats")
def admin_get_notification_stats(notification_id: int, admin: bool = Depends(verify_admin)):
    """Returns detailed read statistics for a specific notification."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,))
    notif = cursor.fetchone()
    if not notif:
        conn.close()
        raise HTTPException(status_code=404, detail="Notification not found")

    cursor.execute("""
    SELECT s.id, s.roll_no, s.name, s.section, nr.read_at
    FROM notification_reads nr
    JOIN students s ON s.id = nr.student_id
    WHERE nr.notification_id = ?
    ORDER BY nr.read_at DESC
    """, (notification_id,))
    readers = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {
        "notification": dict(notif),
        "total_reads": len(readers),
        "readers": readers
    }


# ─────────────────────────────────────────────────────────────────────────
# ADMIN TARGETS CONVENIENCE ENDPOINT
# ─────────────────────────────────────────────────────────────────────────

@router.get("/admin/targets")
def admin_get_targets(admin: bool = Depends(verify_admin)):
    """
    Returns available target scopes (groups, sections, students)
    to populate dropdowns in the notification composer.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Groups
    cursor.execute("""
    SELECT g.id, g.name, g.description, COUNT(m.student_id) AS member_count
    FROM groups g
    LEFT JOIN group_members m ON g.id = m.group_id
    GROUP BY g.id
    ORDER BY g.name ASC
    """)
    groups = [dict(r) for r in cursor.fetchall()]

    # Sections
    cursor.execute("""
    SELECT DISTINCT section
    FROM students
    WHERE section IS NOT NULL AND TRIM(section) != ''
    ORDER BY section ASC
    """)
    sections = [r["section"] for r in cursor.fetchall()]

    # Students (active)
    cursor.execute("""
    SELECT id, roll_no, name, section
    FROM students
    WHERE COALESCE(is_active, 1) = 1
    ORDER BY section ASC, roll_no ASC
    """)
    students = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {
        "groups": groups,
        "sections": sections,
        "students": students
    }


# ─────────────────────────────────────────────────────────────────────────
# ADMIN GROUP MANAGEMENT ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────

@router.get("/admin/groups")
def admin_list_groups(admin: bool = Depends(verify_admin)):
    """Lists all student groups with their member counts."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT g.id, g.name, g.description, g.created_at, COUNT(m.student_id) AS member_count
    FROM groups g
    LEFT JOIN group_members m ON g.id = m.group_id
    GROUP BY g.id
    ORDER BY g.name ASC
    """)
    groups = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return {"groups": groups}


@router.post("/admin/groups")
def admin_create_group(req: CreateGroupRequest, admin: bool = Depends(verify_admin)):
    """Creates a new student group with optional initial member assignments."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name cannot be empty")

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
        INSERT INTO groups (name, description, created_at)
        VALUES (?, ?, datetime('now', 'localtime'))
        """, (name, (req.description or "").strip()))
        group_id = cursor.lastrowid
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"A group with that name already exists or invalid data: {e}")

    if req.student_ids:
        for sid in set(req.student_ids):
            cursor.execute("""
            INSERT OR IGNORE INTO group_members (group_id, student_id, added_at)
            VALUES (?, ?, datetime('now', 'localtime'))
            """, (group_id, sid))

    conn.commit()
    conn.close()

    return {"success": True, "id": group_id, "name": name}


@router.get("/admin/groups/{group_id}")
def admin_get_group_details(group_id: int, admin: bool = Depends(verify_admin)):
    """Returns group metadata along with its full list of member students."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM groups WHERE id = ?", (group_id,))
    group = cursor.fetchone()
    if not group:
        conn.close()
        raise HTTPException(status_code=404, detail="Group not found")

    cursor.execute("""
    SELECT s.id, s.roll_no, s.name, s.section, s.email, gm.added_at
    FROM group_members gm
    JOIN students s ON s.id = gm.student_id
    WHERE gm.group_id = ?
    ORDER BY s.section ASC, s.roll_no ASC
    """, (group_id,))
    members = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {
        "group": dict(group),
        "members": members,
        "member_count": len(members)
    }


@router.put("/admin/groups/{group_id}")
def admin_update_group(group_id: int, req: UpdateGroupRequest, admin: bool = Depends(verify_admin)):
    """Updates group name or description."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM groups WHERE id = ?", (group_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Group not found")

    updates = []
    params = []

    if req.name is not None:
        updates.append("name = ?")
        params.append(req.name.strip())
    if req.description is not None:
        updates.append("description = ?")
        params.append(req.description.strip())

    if updates:
        params.append(group_id)
        try:
            cursor.execute(f"UPDATE groups SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
        except Exception as e:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Error updating group: {e}")

    conn.close()
    return {"success": True, "id": group_id}


@router.delete("/admin/groups/{group_id}")
def admin_delete_group(group_id: int, admin: bool = Depends(verify_admin)):
    """Deletes a group and unlinks all members."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM group_members WHERE group_id = ?", (group_id,))
    cursor.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    conn.commit()
    conn.close()

    return {"success": True, "id": group_id}


@router.post("/admin/groups/{group_id}/members")
def admin_set_group_members(group_id: int, req: GroupMembersRequest, admin: bool = Depends(verify_admin)):
    """Replaces the entire membership list of a group with the given student IDs."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM groups WHERE id = ?", (group_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Group not found")

    # Clear current members and insert new list
    cursor.execute("DELETE FROM group_members WHERE group_id = ?", (group_id,))
    for sid in set(req.student_ids):
        cursor.execute("""
        INSERT OR IGNORE INTO group_members (group_id, student_id, added_at)
        VALUES (?, ?, datetime('now', 'localtime'))
        """, (group_id, sid))

    conn.commit()

    cursor.execute("SELECT COUNT(*) as count FROM group_members WHERE group_id = ?", (group_id,))
    new_count = cursor.fetchone()["count"]
    conn.close()

    return {"success": True, "group_id": group_id, "member_count": new_count}
