import logging
import os
import random
import string
import threading
import time
from pathlib import Path

# ── Logging disabled (no trace) ──
_LOG_DIR = Path(__file__).resolve().parent.parent
log = logging.getLogger("CodePilot")
log.addHandler(logging.NullHandler())

import keyboard
import pyautogui

# Ensure both classes are imported from your computer.py file
from agent.computer import Computer, HackerTyperMode
from agent.gemini import GeminiAgent, GeminiWebError
from agent.stealth_capture import StealthAbort


class CodePilot:
    def __init__(self):
        # WPM takes precedence over TYPE_INTERVAL
        wpm_str = os.getenv("WPM", "").strip()
        if wpm_str and float(wpm_str) > 0:
            type_interval = Computer.wpm_to_interval(float(wpm_str))
            self._wpm = float(wpm_str)
        else:
            type_interval = float(os.getenv("TYPE_INTERVAL", "0.015"))
            self._wpm = None

        self.result_delay = float(os.getenv("RESULT_DELAY", "10"))

        # Auto-close bracket fix (most online editors auto-insert closing brackets)
        fix_auto_close = os.getenv("FIX_AUTO_CLOSE", "true").strip().lower() in ("true", "1", "yes")

        # Hacker Mode settings
        chunk_amount = int(os.getenv("CHUNK_AMOUNT", "3"))
        chunk_type = os.getenv("CHUNK_TYPE", "chars")

        self.agent = GeminiAgent()

        self.computer = Computer(base_interval=type_interval, fix_auto_close=fix_auto_close)
        self.hacker_mode = HackerTyperMode(
            self.computer,
            source_text="",
            chunk_amount=chunk_amount,
            chunk_type=chunk_type
        )

        # ── STATE ──────────────────────────────────────────────────────
        self.problem_screenshots = []
        self.problem = None
        self.solution = None
        self.previous_code = None
        self.failure = None
        self.busy = False
        self._gen_id = 0          # generation counter for model override
        self._active_model_pref = None  # "pro" or "fast"

    # ══════════════════════════════════════════════════════════════════
    # Thread management
    # ══════════════════════════════════════════════════════════════════

    def run_async(self, fn):
        """Run fn in a background thread, respecting busy flag."""
        if self.busy:
            log.warning("run_async BLOCKED: busy=True, fn=%s", fn.__name__)
            print("\n[BUSY] Wait for the current operation.")
            return
        log.info("run_async START: %s", fn.__name__)
        threading.Thread(target=self._safe_run, args=(fn,), daemon=True).start()

    @staticmethod
    def _reset_keyboard_state():
        """Clear stuck modifier keys in the keyboard library.

        When Alt+N hotkeys trigger long operations (typing, generation),
        the keyboard library's internal _pressed_events dict can get stale
        entries for Alt/Shift/Ctrl, preventing subsequent Alt+N combos
        from firing.  Fix: clear the internal state only — no fake
        key-up events (those show up as INJECTED in keystroke analyzers).
        """
        try:
            keyboard._pressed_events.clear()
        except Exception:
            pass

    def _safe_run(self, fn):
        self.busy = True
        log.info("_safe_run BEGIN: %s", fn.__name__)
        try:
            fn()
            log.info("_safe_run OK: %s", fn.__name__)
        except Exception as exc:
            log.error("_safe_run ERROR in %s: %s", fn.__name__, exc, exc_info=True)
            print("\nERROR:", exc)
        finally:
            self.busy = False
            self._reset_keyboard_state()
            log.debug("_safe_run END: busy=False")

    def _start_generation(self, model_preference):
        """Start a generation with model override support.

        If a generation is already running, this increments the generation
        counter so the old one knows to discard its result. Both threads may
        overlap briefly but only the newest result is kept.
        """
        self._gen_id += 1
        my_id = self._gen_id

        def run():
            self.busy = True
            try:
                self._prepare_solution(model_preference, my_id)
            except Exception as exc:
                if my_id == self._gen_id:
                    print(f"\nERROR: {exc}")
            finally:
                # Only release busy if we're still the active generation
                if my_id == self._gen_id:
                    self.busy = False
                    self._reset_keyboard_state()

        threading.Thread(target=run, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════
    # Alt+1: RESET
    # ══════════════════════════════════════════════════════════════════

    def reset_all(self):
        """Alt+1: Clear everything and start fresh."""
        self._gen_id += 1  # invalidate any running generation
        self.problem_screenshots.clear()
        self.problem = None
        self.solution = None
        self.previous_code = None
        self.failure = None
        self.computer.stop()
        self.hacker_mode.abort(silent=True)
        self.busy = False
        print("\n" + "=" * 65)
        print("[Alt+1] RESET — Everything cleared!")
        print("=" * 65)
        print("Start fresh: press Alt+7 to capture screenshots.")

    # ══════════════════════════════════════════════════════════════════
    # Alt+7: CAPTURE SCREENSHOT
    # ══════════════════════════════════════════════════════════════════

    def queue_screenshot(self):
        """Alt+7: Capture screen and add to queue."""
        print("\n" + "=" * 65)
        print("[Alt+7] STEALTH CAPTURE")
        print("=" * 65)

        try:
            image, mime = self.computer.capture_desktop()
        except StealthAbort as e:
            print(f"\n  [WARN] {e}")
            print("  Falling back to direct capture...")
            try:
                image, mime = self.computer.capture_desktop(force=True)
            except Exception as e2:
                print(f"  [ERROR] Fallback capture also failed: {e2}")
                return

        self.problem_screenshots.append((image, mime))
        log.info("Screenshot queued: total=%d", len(self.problem_screenshots))
        print(f"-> Captured! Total in queue: {len(self.problem_screenshots)}")
        print("Alt+7 = more screenshots | Alt+8 = Solve (Pro) | Alt+9 = Solve (Fast)")

    # ══════════════════════════════════════════════════════════════════
    # Alt+8 / Alt+9: ANALYZE + SOLVE (with model override)
    # ══════════════════════════════════════════════════════════════════

    def _prepare_solution(self, model_preference, gen_id):
        """Core analyze + solve pipeline.

        Supports mid-flight model switching: if the user presses the other
        model key while this is running, gen_id will be stale and we bail.
        """
        model = self.agent.get_model_by_preference(model_preference)
        model_name = self.agent._model_name(model)
        self._active_model_pref = model_preference

        if model_preference == "pro":
            tag = "Alt+8/Pro"
        elif model_preference == "api":
            tag = "Alt+9/API"
        else:
            tag = "Alt+9/Fast"
        print(f"\n{'=' * 65}")
        print(f"[{tag}] ANALYZE + SOLVE  ({model_name})")
        print(f"{'=' * 65}")

        need_analyze = True

        # If problem already analyzed and no new screenshots → just re-solve
        if (self.problem
                and self.problem.get("coding_page_visible")
                and not self.problem_screenshots):
            need_analyze = False
            print(f"Re-solving with {model_name} (problem already analyzed)...")

        if need_analyze:
            # Auto-capture if no screenshots queued
            if not self.problem_screenshots:
                print("No screenshots queued. Capturing current screen...")
                try:
                    image, mime = self.computer.capture_desktop()
                    self.problem_screenshots.append((image, mime))
                except StealthAbort as e:
                    print(f"\n  [WARN] {e}")
                    print("  Falling back to direct capture...")
                    try:
                        image, mime = self.computer.capture_desktop(force=True)
                        self.problem_screenshots.append((image, mime))
                    except Exception as e2:
                        print(f"  [ERROR] Fallback capture failed: {e2}")
                        return

            n = len(self.problem_screenshots)
            print(f"[1] Analyzing {n} screen(s) with {model_name}...")

            try:
                self.problem = self.agent.inspect_problem(
                    self.problem_screenshots, force_model=model
                )
            except GeminiWebError as exc:
                print(f"\n[GEMINI ERROR] {exc}")
                print(f"Screenshots preserved ({n} in queue). Press Alt+8/Alt+9 to retry.")
                return

            # ── Check override ──
            if gen_id != self._gen_id:
                print(f"\n[OVERRIDDEN] Switched to different model.")
                return

            ptype = self.problem.get("problem_type", "CODE")
            print(f"\n  Type: {ptype}")
            print(f"  Title: {self.problem.get('title')}")

            if not self.problem.get("coding_page_visible"):
                print("\nNo coding page detected.")
                self.problem_screenshots.clear()
                return

            # ── MCQ path ──
            if ptype == "MCQ":
                correct = self.problem.get("mcq_correct_answer", "?")
                self.solution = f"Answer: {correct}"
                self.problem_screenshots.clear()
                print(f"\n[MCQ DETECTED] Correct answer: {correct}")
                opts = self.problem.get("mcq_options", [])
                for opt in opts:
                    marker = " <<< " if opt.get("label") == correct else ""
                    print(f"  {opt.get('label')}: {opt.get('text')}{marker}")
                # Auto-hover on MCQ answer
                self.hover_mcq_answer()
                self._notify_ready()
                return

        # ── Solve (CODE path) ──
        step = "2" if need_analyze else "1"
        print(f"\n[{step}] Generating solution with {model_name}...")

        try:
            self.solution = self.agent.solve(
                self.problem, self.previous_code, self.failure,
                force_model=model
            )
        except GeminiWebError as exc:
            print(f"\n[GEMINI ERROR] {exc}")
            print(f"Press Alt+8/Alt+9 to retry.")
            return

        # ── Check override ──
        if gen_id != self._gen_id:
            print(f"\n[OVERRIDDEN] Switched to different model.")
            return

        self.problem_screenshots.clear()

        print("\n========== PREPARED CODE ==========\n")
        print(self.solution)
        print("\n===================================")
        print("\nSolution ready!")
        print("  Alt+2 = Auto Type  |  Alt+3 = Hacker Type")
        print("  Alt+8 = Re-solve (Pro)  |  Alt+9 = Re-solve (Fast)")
        self._notify_ready()

    def _notify_ready(self):
        """Silent notification — placeholder for future use."""
        pass

    # Code-like fragments for busy typing — looks like real C++ coding
    _CODE_FRAGMENTS = [
        'int ', 'for ', 'if (', 'while', 'return', 'void ', 'auto ',
        'long ', 'bool ', 'char ', 'const', 'class', 'using',
        'vec', 'arr', 'dp[', 'ans', 'res', 'sum', 'cnt', 'idx',
        'tmp', 'cur', 'nxt', 'prev', 'left', 'mid', 'val',
        'i++', 'j--', 'n-1', '= 0', '+= ', '-= ', '== ', '!= ',
        '(i)', '[j]', '++)', 'max(', 'min(', 'push', 'size',
        '<< ', '>> ', '&& ', '|| ', 'true', 'null', 'endl',
        'cout', 'cin ', 'MOD', '1e9', 'INF', 'n = ', 'm = ',
        'sort', 'swap', 'find', 'pair', 'map<', 'set<',
        '    ', '  ', '; ', ', ', '{ ', '} ', '= ', '+ ',
    ]

    def type_solution_auto(self):
        """Alt+2: Type solution or code-like chars while busy."""
        log.info("type_solution_auto called: busy=%s, solution=%s",
                 self.busy, self.solution is not None)
        # ── Busy mode: type code-like fragments using Interception ──
        if self.busy and not self.solution:
            n_shots = max(1, len(self.problem_screenshots))
            char_count = random.randint(2 + n_shots, 3 + n_shots * 2)
            frag = ''
            while len(frag) < char_count:
                frag += random.choice(self._CODE_FRAGMENTS)
            chars = frag[:char_count]
            log.info("Typing busy fragment: %s", chars)
            self.computer.type_at_current_cursor(chars)
            return

        if not self.solution:
            log.info("No solution ready")
            print("\nNo solution ready. Press Alt+8/Alt+9 first.")
            return

        log.info("Starting auto-type thread")
        # ── Real typing → run in background thread ──
        self.run_async(self._do_auto_type)

    def _do_auto_type(self):
        self.hacker_mode.abort(silent=True)
        log.info("_do_auto_type started")
        print("\n" + "=" * 65)
        print("[Alt+2] AUTO MODE: TYPING SOLUTION")
        print("=" * 65)

        # ── Move mouse to editor and click to focus ──
        self._click_into_editor()

        # ── Select all existing code (Ctrl+A) ──
        log.info("Sending Ctrl+A to select all")
        self.computer._send_key_combo("ctrl", "a")
        time.sleep(0.2)

        print("Starting in 1 second...")
        time.sleep(1)
        # Get existing editor code to skip matching lines
        existing = None
        if self.problem and isinstance(self.problem, dict):
            existing = self.problem.get("editor_current_code", None)
        log.info("Typing solution (%d chars)", len(self.solution))
        self.computer.type_at_current_cursor(self.solution, existing_text=existing)
        log.info("Auto-typing complete")
        print("\n[DONE] Auto-typing complete.")
        print("  Alt+0 = Analyze result (if failed)")
        print("  Alt+7 = Next question (if passed)")

    def _click_into_editor(self):
        """Move mouse to editor and click using Win32 API (bypasses secure browser blocks)."""
        import ctypes
        screen_w, screen_h = pyautogui.size()

        # Use AI-detected editor position, or fall back to reasonable default
        ex = 0.70
        ey = 0.40
        if self.problem and isinstance(self.problem, dict):
            px = self.problem.get("editor_click_x", 0)
            py = self.problem.get("editor_click_y", 0)
            if px > 0.1 and py > 0.1:
                ex = px
                ey = py

        target_x = int(screen_w * (ex + random.uniform(-0.02, 0.02)))
        target_y = int(screen_h * (ey + random.uniform(-0.02, 0.02)))
        log.info("Clicking editor at (%d, %d) from detected (%.2f, %.2f)",
                 target_x, target_y, ex, ey)

        # Use SetCursorPos + mouse_event (lower level than SendInput)
        ctypes.windll.user32.SetCursorPos(target_x, target_y)
        time.sleep(random.uniform(0.05, 0.12))

        # mouse_event: MOUSEEVENTF_LEFTDOWN=0x02, MOUSEEVENTF_LEFTUP=0x04
        ctypes.windll.user32.mouse_event(0x02, 0, 0, 0, 0)
        time.sleep(random.uniform(0.03, 0.06))
        ctypes.windll.user32.mouse_event(0x04, 0, 0, 0, 0)
        time.sleep(random.uniform(0.1, 0.2))
        log.info("Editor click done")
        print(f"  Clicked editor at ({target_x}, {target_y})")

    def _auto_analyze_result(self):
        """Automatically capture screen and analyze result after typing."""
        print("\n" + "=" * 65)
        print("[AUTO] ANALYZING RESULT")
        print("=" * 65)

        # Capture screen
        try:
            image, mime = self.computer.capture_desktop()
        except StealthAbort as e:
            try:
                image, mime = self.computer.capture_desktop(force=True)
            except Exception:
                print("  [ERROR] Could not capture screen for analysis.")
                return

        # Analyze
        try:
            result = self.agent.inspect_result(image, mime)
        except GeminiWebError as exc:
            print(f"\n[WARN] Auto-analysis failed: {exc}")
            print("Press Alt+0 to try manually.")
            return

        status = result.get("status", "UNKNOWN")
        print(f"\nStatus: {status}")
        print(f"Evidence: {result.get('evidence')}")

        if status == "ACCEPTED":
            print("\n================ SOLVED ================")
            self.previous_code = None
            self.failure = None
            self.problem = None
            self.solution = None
            self.problem_screenshots.clear()
            print("Ready for next question. Press Alt+7 to capture.")
            self._notify_ready()
            return

        if status in {"RUNNING", "NO_RESULT"}:
            print("\nResult not visible yet. Press Alt+0 to check again.")
            return

        if status == "UNKNOWN":
            print("\nResult ambiguous. Press Alt+0 to retry.")
            return

        # FAILED — auto-generate corrected solution
        self.failure = result
        self.previous_code = self.solution
        print("\nFailure detected. Generating corrected solution...")

        model_pref = self._active_model_pref or "pro"
        model = self.agent.get_model_by_preference(model_pref)

        try:
            self.solution = self.agent.solve(
                self.problem, self.previous_code, self.failure,
                force_model=model
            )
        except GeminiWebError as exc:
            print(f"\n[GEMINI ERROR] {exc}")
            print("Press Alt+8/Alt+9 to retry.")
            return

        print("\n========== CORRECTED CODE ==========\n")
        print(self.solution)
        print("\n====================================")
        print("\nAlt+2 = Auto Type  |  Alt+3 = Hacker Type")
        self._notify_ready()

    # ══════════════════════════════════════════════════════════════════
    # Alt+3: HACKER TYPE
    # ══════════════════════════════════════════════════════════════════

    def type_solution_hacker(self):
        """Alt+3: Arm hacker mode — mash keys to type code."""
        if not self.solution:
            print("\nNo solution ready. Press Alt+8/Alt+9 first.")
            return
        print("\n" + "=" * 65)
        print("[Alt+3] HACKER MODE: ARMED")
        print("=" * 65)
        self.hacker_mode.source_text = self.solution
        self.hacker_mode.start_or_restart()

    # ══════════════════════════════════════════════════════════════════
    # Alt+4: MCQ HOVER
    # ══════════════════════════════════════════════════════════════════

    def hover_mcq_answer(self):
        """Alt+4: Move mouse to the correct MCQ answer and click."""
        import ctypes
        log.info("hover_mcq_answer called: problem=%s", self.problem is not None)
        if not self.problem:
            log.info("No problem analyzed")
            print("\nNo problem analyzed. Press Alt+8/Alt+9 first.")
            return
        if self.problem.get("problem_type") != "MCQ":
            log.info("Not an MCQ (type=%s)", self.problem.get("problem_type"))
            print("\nNot an MCQ. Use Alt+2/Alt+3 to type code.")
            return
        correct = self.problem.get("mcq_correct_answer")
        options = self.problem.get("mcq_options", [])
        log.info("MCQ correct=%s, options=%d", correct, len(options))
        target = None
        for opt in options:
            if opt.get("label") == correct:
                target = opt
                break
        if not target:
            log.warning("No position found for answer '%s'", correct)
            print(f"\nCould not find position for answer '{correct}'.")
            return

        x_pct = float(target.get("x_percent", 0.3))
        y_pct = float(target.get("y_percent", 0.5))
        screen_w, screen_h = pyautogui.size()
        target_x = int(screen_w * x_pct)
        target_y = int(screen_h * y_pct)
        log.info("Moving to MCQ (%d, %d) for answer %s", target_x, target_y, correct)

        # Use SetCursorPos (Win32 API, bypasses secure browser blocks)
        ctypes.windll.user32.SetCursorPos(target_x, target_y)
        time.sleep(random.uniform(0.1, 0.2))

        # Click the answer
        ctypes.windll.user32.mouse_event(0x02, 0, 0, 0, 0)  # LEFTDOWN
        time.sleep(random.uniform(0.04, 0.08))
        ctypes.windll.user32.mouse_event(0x04, 0, 0, 0, 0)  # LEFTUP

        log.info("MCQ click done at (%d, %d)", target_x, target_y)
        print(f"\n[MCQ] Clicked: {correct} — {target.get('text', '')}")

    # ══════════════════════════════════════════════════════════════════
    # Alt+5: PAUSE / RESUME
    # ══════════════════════════════════════════════════════════════════

    def universal_pause(self):
        if self.hacker_mode.armed:
            self.hacker_mode.toggle_pause()
        else:
            if self.computer.is_paused:
                self.computer.resume()
                print("\n[RESUMED]")
            else:
                self.computer.pause()
                print("\n[PAUSED] Press Alt+5 again to resume.")

    # ══════════════════════════════════════════════════════════════════
    # Alt+6: ABORT
    # ══════════════════════════════════════════════════════════════════

    def universal_abort(self):
        self.computer.stop()
        self.hacker_mode.abort()
        print("\n[ABORTED] All typing stopped.")

    # ══════════════════════════════════════════════════════════════════
    # Alt+0: ANALYZE RESULT
    # ══════════════════════════════════════════════════════════════════

    def analyze_result(self):
        print("\n" + "=" * 65)
        print("[Alt+0] ANALYZE CURRENT RESULT")
        print("=" * 65)

        try:
            image, mime = self.computer.capture_desktop()
        except StealthAbort as e:
            print(f"\n  [WARN] {e}")
            print("  Falling back to direct capture...")
            try:
                image, mime = self.computer.capture_desktop(force=True)
            except Exception as e2:
                print(f"  [ERROR] Fallback capture failed: {e2}")
                return

        print("[1] Analyzing result...")
        # Auto-retry once on transient error
        result = None
        for retry in range(2):
            try:
                result = self.agent.inspect_result(image, mime)
                break
            except GeminiWebError as exc:
                if retry == 0:
                    print(f"\n[RETRY] {exc}")
                    print("[RETRY] Retrying in 3s...")
                    time.sleep(3)
                else:
                    print(f"\n[GEMINI ERROR] {exc}")
                    print("Press Alt+0 to try again.")
                    return

        print("\nStatus:", result.get("status"))
        print("Evidence:", result.get("evidence"))

        status = result.get("status", "UNKNOWN")

        if status == "ACCEPTED":
            print("\n================ SOLVED ================")
            self.previous_code = None
            self.failure = None
            self.problem = None
            self.solution = None
            self.problem_screenshots.clear()
            print("Ready for next question. Press Alt+7 to capture.")
            self._notify_ready()
            return

        if status in {"RUNNING", "NO_RESULT"}:
            print("\nNo final result visible. Press Alt+0 again when ready.")
            return

        if status == "UNKNOWN":
            print("\nResult is ambiguous. Stopping rather than guessing.")
            return

        self.failure = result
        self.previous_code = self.solution

        print("\nFailure detected. Generating corrected solution...")

        # Use whichever model was last active
        model_pref = self._active_model_pref or "pro"
        model = self.agent.get_model_by_preference(model_pref)

        try:
            self.solution = self.agent.solve(
                self.problem, self.previous_code, self.failure,
                force_model=model
            )
        except GeminiWebError as exc:
            print(f"\n[GEMINI ERROR] {exc}")
            print("Press Alt+8/Alt+9 to retry.")
            return

        print("\n========== CORRECTED CODE ==========\n")
        print(self.solution)
        print("\n====================================")
        print("\nAlt+2 = Auto Type  |  Alt+3 = Hacker Type")
        self._notify_ready()

    # ══════════════════════════════════════════════════════════════════
    # STARTUP
    # ══════════════════════════════════════════════════════════════════

    def start(self):
        pro_name = self.agent._model_name(
            self.agent.get_model_by_preference("pro"))
        fast_name = self.agent._model_name(
            self.agent.get_model_by_preference("fast"))
        speed = f"WPM={self._wpm:.0f}" if self._wpm else \
                f"interval={self.computer.base_interval:.3f}s"

        print("=" * 65)
        print("              CodePilot V14 - Advanced Gemini Agent")
        print("=" * 65)
        print(f"\n  Pro model  : {pro_name}")
        print(f"  Fast model : {fast_name}")
        print(f"  Typing     : {speed}")
        print("\n  Hotkeys:")
        print("    Alt+1  = RESET (clear all, start fresh)")
        print("    Alt+2  = TYPE solution (Auto Mode)")
        print("         \\-- while processing: types random chars")
        print("    Alt+3  = TYPE solution (Hacker Mode)")
        print("    Alt+4  = MCQ HOVER (move mouse to answer)")
        print("    Alt+5  = PAUSE / RESUME typing")
        print("    Alt+6  = ABORT typing")
        print("    Alt+7  = Capture screenshot to queue")
        print("    Alt+8  = Analyze + Solve (Web Pro)")
        print("    Alt+9  = Analyze + Solve (Official API)")
        print("         \\-- Alt+8/Alt+9 override each other mid-flight")
        print("    Alt+0  = Analyze result (Pass/Fail)")
        print("\n  ESC = stop")
        print("=" * 65)

        from agent.computer import _USE_INTERCEPTION
        log.info("=== CodePilot STARTED === interception=%s, pro=%s, fast=%s",
                 _USE_INTERCEPTION, pro_name, fast_name)

        # ── System-level hotkeys (unblockable by any application) ──
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        MOD_ALT = 0x0001
        MOD_NOREPEAT = 0x4000
        WM_HOTKEY = 0x0312

        # Virtual key codes: 0=0x30, 1=0x31, ..., 9=0x39, ESC=0x1B
        hotkeys = {
            1:  (0x31, self.reset_all),              # Alt+1 RESET
            2:  (0x32, self.type_solution_auto),      # Alt+2 TYPE
            3:  (0x33, self.type_solution_hacker),    # Alt+3 HACKER
            4:  (0x34, self.hover_mcq_answer),        # Alt+4 MCQ
            5:  (0x35, self.universal_pause),          # Alt+5 PAUSE
            6:  (0x36, self.universal_abort),          # Alt+6 ABORT
            7:  (0x37, lambda: self.run_async(self.queue_screenshot)),  # Alt+7
            8:  (0x38, lambda: self._start_generation("pro")),         # Alt+8
            9:  (0x39, lambda: self._start_generation("api")),         # Alt+9
            10: (0x30, lambda: self.run_async(self.analyze_result)),   # Alt+0
            99: (0x1B, None),                          # ESC = quit
        }

        for hk_id, (vk, _) in hotkeys.items():
            if not user32.RegisterHotKey(None, hk_id, MOD_ALT | MOD_NOREPEAT, vk):
                log.warning("Failed to register hotkey id=%d vk=0x%X", hk_id, vk)
            else:
                log.info("Registered hotkey id=%d vk=0x%X", hk_id, vk)

        # ESC without Alt
        if not user32.RegisterHotKey(None, 99, MOD_NOREPEAT, 0x1B):
            log.warning("Failed to register ESC hotkey")

        log.info("All system hotkeys registered (RegisterHotKey)")

        # ── Message pump — waits for hotkey events ──
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY:
                    hk_id = msg.wParam
                    if hk_id == 99:
                        log.info("ESC pressed, breaking message loop")
                        break
                    if hk_id in hotkeys:
                        vk, handler = hotkeys[hk_id]
                        name = {1:'RESET',2:'TYPE',3:'HACKER',4:'MCQ',5:'PAUSE',
                                6:'ABORT',7:'SCREENSHOT',8:'PRO',9:'API',10:'RESULT'}.get(hk_id,'?')
                        log.info("HOTKEY Alt+%s pressed (busy=%s, solution=%s)",
                                 name, self.busy, self.solution is not None)
                        try:
                            handler()
                        except Exception as e:
                            log.error("Hotkey handler error: %s", e, exc_info=True)
        finally:
            # Unregister all hotkeys
            for hk_id in hotkeys:
                user32.UnregisterHotKey(None, hk_id)
            log.info("All hotkeys unregistered")
            try:
                self.agent.close()
            except Exception:
                pass
            self._cleanup_traces()
            print("\nStopping CodePilot...")

    @staticmethod
    def _cleanup_traces():
        """Remove ALL traces — zero files left behind."""
        import shutil
        root = Path(__file__).resolve().parent.parent
        # Delete config, logs, session folder
        for f in [root / ".env.example", root / "codepilot.log"]:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass
        # Delete session/ (screenshots)
        session_dir = root / "session"
        try:
            shutil.rmtree(session_dir, ignore_errors=True)
        except Exception:
            pass
        # Delete all __pycache__ directories
        for d in root.rglob("__pycache__"):
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass
        # Delete techno.exe (renamed python copy)
        techno = root / ".venv" / "Scripts" / "techno.exe"
        try:
            techno.unlink(missing_ok=True)
        except Exception:
            pass


def main():
    try:
        CodePilot().start()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print("\nStartup error:", exc)


if __name__ == "__main__":
    main()