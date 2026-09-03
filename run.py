"""
PyMentor Server Runner
Starts the FastAPI server with Uvicorn on port 8000.
"""

import sys
import os

# Fix Windows console encoding for UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import uvicorn

# Ensure the lecture directory is in sys.path
lecture_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(lecture_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("      PyMentor - AI-Powered Student Practice Platform")
    print("=" * 60)
    print(" * Local Access  : http://localhost:8000")
    print(" * Network Access: http://127.0.0.1:8000")
    print(" * Ready for students to practice & receive AI mentoring!")
    print("=" * 60 + "\n")

    uvicorn.run("pymentor.backend.main:app", host="0.0.0.0", port=8000, reload=False)
