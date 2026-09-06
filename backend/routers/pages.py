"""
Page-serving routes and static HTML delivery.
"""

import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

try:
    from pymentor.backend.config import FRONTEND_DIR
except ImportError:
    from backend.config import FRONTEND_DIR

router = APIRouter(tags=["pages"])


@router.get("/favicon.ico")
def serve_favicon_ico():
    """Serve standard favicon.ico file."""
    ico_file = os.path.join(FRONTEND_DIR, "favicon.ico")
    if os.path.exists(ico_file):
        return FileResponse(ico_file, media_type="image/x-icon", headers={"Cache-Control": "no-cache, must-revalidate"})
    raise HTTPException(status_code=404, detail="Favicon not found")


@router.get("/favicon.svg")
def serve_favicon_svg():
    """Serve scalable vector favicon.svg file."""
    svg_file = os.path.join(FRONTEND_DIR, "favicon.svg")
    if os.path.exists(svg_file):
        return FileResponse(svg_file, media_type="image/svg+xml", headers={"Cache-Control": "no-cache, must-revalidate"})
    raise HTTPException(status_code=404, detail="Favicon not found")


@router.get("/logo.svg")
def serve_logo_svg():
    """Serve scalable vector logo.svg brand asset."""
    svg_file = os.path.join(FRONTEND_DIR, "logo.svg")
    if os.path.exists(svg_file):
        return FileResponse(svg_file, media_type="image/svg+xml", headers={"Cache-Control": "no-cache, must-revalidate"})
    raise HTTPException(status_code=404, detail="Logo not found")


@router.get("/")
def serve_root():
    """Redirect root to /problems."""
    return RedirectResponse(url="/problems")


@router.get("/problems")
def serve_problems():
    """Serve the problems browser page."""
    problems_file = os.path.join(FRONTEND_DIR, "problems.html")
    if os.path.exists(problems_file):
        return FileResponse(problems_file)
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Python Practice API is running. Frontend not found."}


@router.get("/login")
def serve_login():
    """Serve the login page."""
    login_file = os.path.join(FRONTEND_DIR, "login.html")
    if os.path.exists(login_file):
        return FileResponse(login_file)
    raise HTTPException(status_code=404, detail="Login page not found")


@router.get("/practice")
def serve_practice():
    """Serve the code practice page."""
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Practice page not found")


@router.get("/profile")
def serve_profile():
    """Serve the profile dashboard."""
    profile_file = os.path.join(FRONTEND_DIR, "profile.html")
    if os.path.exists(profile_file):
        return FileResponse(profile_file)
    return {"message": "Profile page not found."}


@router.get("/admin")
def serve_admin():
    """Serve the admin dashboard."""
    admin_file = os.path.join(FRONTEND_DIR, "admin.html")
    if os.path.exists(admin_file):
        return FileResponse(admin_file)
    return {"message": "Admin page not found."}
