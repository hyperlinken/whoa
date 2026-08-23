from __future__ import annotations

import base64
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv


def load_environment(root: Path) -> None:
    env_file = root / ".env.example"
    template = root / "env.template"
    if not env_file.exists() and template.exists():
        shutil.copy2(template, env_file)
    load_dotenv(str(env_file if env_file.exists() else template))

    enc = os.getenv("GEMINI_API_KEY_ENC", "").strip()
    if enc and not os.getenv("GEMINI_API_KEY", "").strip():
        try:
            os.environ["GEMINI_API_KEY"] = base64.b64decode(enc).decode()
        except (ValueError, UnicodeDecodeError):
            pass


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    load_environment(root)

    from codepilot.application.app import CodePilotApplication
    app = CodePilotApplication()
    try:
        app.start()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print("\nStartup error:", exc)
    finally:
        app.close()
