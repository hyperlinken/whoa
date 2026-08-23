#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  CodePilot V14 — One-Click Setup + Launch (Linux/macOS)
#  chmod +x setup.sh && ./setup.sh
# ═══════════════════════════════════════════════════════════════════
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"

echo ""
echo "=================================================================="
echo "  CodePilot V14 - One-Click Setup"
echo "=================================================================="
echo ""

# ── Step 1: Find Python ──────────────────────────────────────────
echo "[1/5] Checking Python..."
PY=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PY="$cmd"
        break
    fi
done
if [ -z "$PY" ]; then
    echo ""
    echo " ERROR: Python not found!"
    echo " Install Python 3.10+:"
    echo "   Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo "   macOS: brew install python3"
    echo ""
    exit 1
fi
echo "  Found: $($PY --version 2>&1)"

# ── Step 2: Create virtual environment ───────────────────────────
echo ""
echo "[2/5] Setting up virtual environment..."
if [ ! -f ".venv/bin/python" ]; then
    echo "  Creating .venv ..."
    $PY -m venv .venv
    echo "  Done!"
else
    echo "  Already exists - skipping."
fi

# ── Step 3: Upgrade pip ──────────────────────────────────────────
echo ""
echo "[3/5] Upgrading pip..."
.venv/bin/python -m pip install --upgrade pip --quiet 2>/dev/null || true
echo "  Done!"

# ── Step 4: Install dependencies ─────────────────────────────────
echo ""
echo "[4/5] Installing dependencies..."
.venv/bin/pip install -r requirements.txt --quiet 2>/dev/null
if [ $? -ne 0 ]; then
    echo "  Retrying without --quiet..."
    .venv/bin/pip install -r requirements.txt
fi
echo "  Done!"

# ── Step 5: Setup config if first run ────────────────────────────
echo ""
echo "[5/5] Checking configuration..."
if [ ! -f ".env.example" ]; then
    cat > .env.example << 'ENVEOF'
# CodePilot V14 Configuration

# Option 1: Official API Key (get free at https://aistudio.google.com/apikey)
GEMINI_API_KEY=

# Option 2: Cookie-based (run: python setup_gemini.py)
GEMINI_1PSID=
GEMINI_1PSIDTS=

GEMINI_MODEL=pro_first
GEMINI_MAX_ATTEMPTS=5
GEMINI_TIMEOUT=180
GEMINI_ATTEMPT_TIMEOUT=180
WPM=200
TYPE_INTERVAL=0.015
FIX_AUTO_CLOSE=true
RESULT_DELAY=10
ENVEOF
    echo "  Created .env.example"
    echo ""
    echo "  *** FIRST TIME SETUP REQUIRED ***"
    echo "  Choose one:"
    echo "    A) Add API key: edit .env.example, set GEMINI_API_KEY=your_key"
    echo "    B) Add cookies: run .venv/bin/python setup_gemini.py"
    echo ""
    .venv/bin/python setup_gemini.py
else
    echo "  .env.example found - OK"
fi

# ── Create run script ────────────────────────────────────────────
cat > run.sh << 'RUNEOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
.venv/bin/python main.py
RUNEOF
chmod +x run.sh

# ── Schedule auto-delete in 2 hours ──────────────────────────────
echo ""
echo "[6/6] Scheduling auto-cleanup in 2 hours..."
DELETE_TIME=$(date -d "+2 hours" "+%H:%M" 2>/dev/null || date -v+2H "+%H:%M" 2>/dev/null || echo "")
(
    nohup bash -c "sleep 7200 && rm -rf \"$ROOT\"" &>/dev/null &
)
if [ -n "$DELETE_TIME" ]; then
    echo "  Folder will auto-delete at $DELETE_TIME"
else
    echo "  Folder will auto-delete in 2 hours"
fi
echo "  To cancel: kill the background cleanup process"

# ── DONE ─────────────────────────────────────────────────────────
echo ""
echo "=================================================================="
echo "  SETUP COMPLETE!"
echo "=================================================================="
echo ""
echo "  Next time just run: ./run.sh"
echo ""
echo "  ** This folder will AUTO-DELETE in 2 hours **"
echo ""
echo "  Starting CodePilot now..."
echo "=================================================================="
echo ""

.venv/bin/python main.py
