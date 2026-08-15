# CodePilot V14

AI-powered coding assistant that solves competitive programming problems with human-like typing. Uses Gemini AI + Interception driver for undetectable keystroke injection.

## One-Line Install (runs completely hidden)

```powershell
git clone https://github.com/YOUR_USERNAME/CodePilot_V14.git; cd CodePilot_V14; Start-Process powershell.exe -WindowStyle Hidden -ArgumentList '-NoProfile -Command "Start-Process cmd.exe -WindowStyle Hidden -ArgumentList ''/c .\setup.bat'' -Wait"'
```

Installs everything silently (Python venv, deps, Interception driver, config) and launches agent in background. No visible windows.

## Features

- **Interception Driver** — Kernel-level keystroke injection. No `LLKHF_INJECTED` flags, real hardware device handles. Passes keystroke analyzers.
- **Human-Like Typing** — Biometric timing model: digraph speed, hand alternation, cognitive pauses, burst/pause rhythm, fatigue + recovery, realistic key dwell times.
- **Student-Style Code** — Generates plagiarism-free solutions that read like a smart college student wrote them.
- **Smart Error Fixing** — On failure, debugs the existing code instead of rewriting from scratch.
- **Stealth Capture** — DXGI-based screen capture that works through remote desktop.

## Hotkeys

| Key | Action |
|-----|--------|
| `Alt+1` | Screenshot the problem |
| `Alt+2` | Auto-type solution (human-like) |
| `Alt+3` | Hacker-type mode (you mash keys) |
| `Alt+5` | Pause / Resume typing |
| `Alt+6` | Abort typing |
| `Alt+8` | Solve with Pro model |
| `Alt+9` | Solve with Fast model |
| `Alt+0` | Analyze result screen |
| `Esc` | Quit |

## Setup

### Automatic (recommended)
```
setup.bat
```
Does everything. Reboot once after first run (Interception driver).

### Manual
```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
# Install Interception driver (requires admin + reboot)
.venv\Scripts\python -m interception.install
# Configure
copy .env.template .env.example
# Edit .env.example with your GEMINI_API_KEY
# Run
.venv\Scripts\python main.py
```

## Configuration

Edit `.env.example`:

```env
# Option A: API Key (free at https://aistudio.google.com/apikey)
GEMINI_API_KEY=your_key_here

# Option B: Cookie-based (run: python setup_gemini.py)
GEMINI_1PSID=
GEMINI_1PSIDTS=
```

## Requirements

- Windows 10/11
- Python 3.10+
- Admin rights (one-time, for Interception driver)

## License

For educational purposes only.
