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

import socket
import uvicorn

# Ensure both current directory and parent directory are in sys.path
app_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(app_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

def get_network_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    net_ip = get_network_ip()
    print("\n" + "=" * 60)
    print("      PyMentor - AI-Powered Student Practice Platform")
    print("=" * 60)
    print(" * Local Access  : http://localhost:8000")
    print(f" * Network Access: http://{net_ip}:8000")
    print(" * Audit Logging : logs.txt (live terminal + file logging)")
    print(" * Ready for students to practice & receive AI mentoring!")
    print("=" * 60 + "\n")

    try:
        from pymentor.backend.main import app
    except ImportError:
        from backend.main import app

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
