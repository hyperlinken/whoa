from getpass import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".env.example"

def set_value(text, key, value):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.lstrip("# ")
        if stripped.startswith(key + "="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"

def main():
    print("=" * 72)
    print("CodePilot V14 - Setup")
    print("=" * 72)

    print("\nYou need at least ONE of these (both is best):\n")
    print("  A) API Key  — fast, reliable, works everywhere")
    print("     Get FREE at: https://aistudio.google.com/apikey\n")
    print("  B) Cookies  — unlimited, no rate limits, uses web session")
    print("     Sign into gemini.google.com, F12 → Cookies\n")

    # ── API Key ──
    print("-" * 72)
    api_key = input("API Key (paste key, or Enter to skip): ").strip()

    # ── Cookies ──
    print("-" * 72)
    print("For cookies: F12 → Application → Cookies → gemini.google.com")
    psid = getpass("__Secure-1PSID (or Enter to skip): ").strip()
    psidts = ""
    if psid:
        psidts = getpass("__Secure-1PSIDTS (or Enter to skip): ").strip()

    if not api_key and not psid:
        print("\n[ERROR] You must provide at least an API key OR cookies.")
        print("  Get a free API key at: https://aistudio.google.com/apikey")
        raise SystemExit(1)

    # ── Proxy ──
    print("-" * 72)
    print("If you're on a college/corporate network behind a proxy:")
    print("  Examples: http://proxy.college.edu:8080")
    print("            http://user:pass@proxy:3128")
    print("            socks5://proxy:1080")
    proxy = input("Proxy URL (or Enter to skip): ").strip()

    # ── Save ──
    text = ENV.read_text(encoding="utf-8")
    if api_key:
        text = set_value(text, "GEMINI_API_KEY", api_key)
    if psid:
        text = set_value(text, "GEMINI_1PSID", psid)
        text = set_value(text, "GEMINI_1PSIDTS", psidts)
    if proxy:
        text = set_value(text, "HTTP_PROXY", proxy)
        text = set_value(text, "HTTPS_PROXY", proxy)
    ENV.write_text(text, encoding="utf-8")

    print(f"\nSaved: {ENV}")
    if api_key and psid:
        print("Mode: Cookies (primary) + API (fallback)")
    elif psid:
        print("Mode: Cookies only (add API key for fallback)")
    else:
        print("Mode: API key only")
    if proxy:
        print(f"Proxy: {proxy}")
    print("Run: python main.py")

if __name__ == "__main__":
    main()
