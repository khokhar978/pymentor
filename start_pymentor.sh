#!/usr/bin/env bash
# PyMentor - Automated Linux Mint / Ubuntu Startup Script

set -e

# Change directory to the script's directory
cd "$(dirname "$0")"

echo "============================================================"
echo "       PyMentor - Linux Automated Startup & Environment"
echo "============================================================"
echo ""

# 1. Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed on this system!"
    echo "Please install it using:"
    echo "    sudo apt update && sudo apt install -y python3 python3-pip python3-venv"
    exit 1
fi

echo "[OK] Found Python: $(python3 --version)"

# 2. Setup / Activate Virtual Environment (PEP 668 safe on Linux Mint 21/22)
if [ ! -d "venv" ]; then
    echo "[*] Creating Python virtual environment (venv)..."
    python3 -m venv venv || {
        echo "[ERROR] Failed to create virtual environment."
        echo "You may need to install python3-venv:"
        echo "    sudo apt update && sudo apt install -y python3-venv"
        exit 1
    }
fi

echo "[*] Activating virtual environment..."
source venv/bin/activate

# 3. Check and install dependencies
echo "[*] Checking and installing dependencies..."
pip install --upgrade pip > /dev/null 2>&1 || true
pip install -r requirements.txt

echo "[OK] All dependencies ready."
echo ""

# 4. Launch Server
echo "[*] Launching PyMentor server..."
echo ""
python3 run.py
