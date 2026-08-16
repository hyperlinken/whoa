import ctypes
import ctypes.wintypes
import math
import random
import re
import string
import threading
import time
import queue

import keyboard
import pyautogui

# ===========================================================================
# CONFIGURATION
# ===========================================================================

# Configure Hacker Mode behavior (when you mash keys)
CHUNK_AMOUNT = 3
CHUNK_TYPE = 'chars'  # Options: 'chars', 'words', 'lines'

SOURCE_TEXT = """def classify(n):
    if n < 0:
        return "negative"
    elif n == 0:
        return "zero"
    else:
        return "positive"
"""

# ===========================================================================
# WINDOWS LOW-LEVEL KEY INPUT — with proper VK + scan codes
# ===========================================================================

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP       = 0x0002
KEYEVENTF_UNICODE     = 0x0004

# Virtual-key constants
VK_BACK    = 0x08
VK_TAB     = 0x09
VK_RETURN  = 0x0D
VK_SHIFT   = 0x10
VK_CONTROL = 0x11
VK_MENU    = 0x12   # Alt
VK_ESCAPE  = 0x1B
VK_SPACE   = 0x20
VK_HOME    = 0x24
VK_END     = 0x23
VK_DELETE  = 0x2E
VK_LSHIFT  = 0xA0

# Keys that require KEYEVENTF_EXTENDEDKEY flag
_EXTENDED_VKS = frozenset({
    0x21, 0x22, 0x23, 0x24,          # PageUp, PageDn, End, Home
    0x25, 0x26, 0x27, 0x28,          # Arrow keys
    0x2D, 0x2E,                      # Insert, Delete
    0x5B, 0x5C,                      # LWin, RWin
    0xA1, 0xA3, 0xA5,                # RShift, RControl, RMenu
})


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ('wVk',         ctypes.wintypes.WORD),
        ('wScan',       ctypes.wintypes.WORD),
        ('dwFlags',     ctypes.wintypes.DWORD),
        ('time',        ctypes.wintypes.DWORD),
        ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT(ctypes.Structure):
    """Matches Windows INPUT struct — 40 bytes on 64-bit.

    The union padding is 32 bytes (size of MOUSEINPUT on 64-bit)
    so ctypes.sizeof(_INPUT) == 40, matching the OS expectation.
    """
    class _UNION(ctypes.Union):
        _fields_ = [('ki', _KEYBDINPUT), ('padding', ctypes.c_byte * 32)]
    _anonymous_ = ('_u',)
    _fields_ = [
        ('type', ctypes.wintypes.DWORD),
        ('_u', _UNION),
    ]


_SendInput = ctypes.windll.user32.SendInput

# Map char → VK code (+ modifier bits in high byte)
_VkKeyScanW = ctypes.windll.user32.VkKeyScanW
_VkKeyScanW.restype = ctypes.c_short
_VkKeyScanW.argtypes = [ctypes.wintypes.WCHAR]

# Map VK → hardware scan code
_MapVirtualKeyW = ctypes.windll.user32.MapVirtualKeyW
_MapVirtualKeyW.restype  = ctypes.wintypes.UINT
_MapVirtualKeyW.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.UINT]
_MAPVK_VK_TO_VSC = 0


def _send_key(vk, scan=None, key_up=False):
    """Send a single key event with proper VK *and* scan code.

    This produces events that pass scan-code analysis:
      - wVk  = virtual key code
      - wScan = hardware scan code from MapVirtualKeyW
      - KEYEVENTF_EXTENDEDKEY set for nav / editing keys
    """
    if scan is None:
        scan = _MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC)
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk   = vk
    inp.ki.wScan = scan
    flags = 0
    if key_up:
        flags |= KEYEVENTF_KEYUP
    if vk in _EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp.ki.dwFlags = flags
    _SendInput(1, ctypes.pointer(inp), ctypes.sizeof(_INPUT))


def _press_key(vk, scan=None):
    """Press and release a key with proper scan code (SendInput fallback)."""
    if scan is None:
        scan = _MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC)
    _send_key(vk, scan, False)
    time.sleep(0.008)
    _send_key(vk, scan, True)


# ===========================================================================
# INTERCEPTION DRIVER — kernel-level input (no LLKHF_INJECTED, real hDevice)
# ===========================================================================

_USE_INTERCEPTION = False
_icp = None
_icp_ctx = None
_icp_get_key_info = None
_IcpKeyStroke = None
_ICP_KEY_DOWN = None
_ICP_KEY_UP = None
_ICP_KEY_E0 = None
_ICP_SHIFT_DN = None
_ICP_SHIFT_UP = None

try:
    import interception as _icp
    _icp.auto_capture_devices(keyboard=True, mouse=False)
    _USE_INTERCEPTION = True

    # Pre-compute raw stroke objects to bypass library's _send_with_mods
    from interception.inputs import _g_context as _icp_ctx
    from interception._keycodes import get_key_information as _icp_get_key_info
    from interception.strokes import KeyStroke as _IcpKeyStroke
    from interception.constants import KeyFlag as _IcpKeyFlag
    _ICP_KEY_DOWN = _IcpKeyFlag.KEY_DOWN
    _ICP_KEY_UP = _IcpKeyFlag.KEY_UP
    _ICP_KEY_E0 = _IcpKeyFlag.KEY_E0
    # Pre-built Shift strokes (scan code 0x2A = Left Shift)
    _ICP_SHIFT_DN = _IcpKeyStroke(0x2A, _IcpKeyFlag.KEY_DOWN)
    _ICP_SHIFT_UP = _IcpKeyStroke(0x2A, _IcpKeyFlag.KEY_UP)
except Exception:
    _icp = None

# ===========================================================================
# HUMAN-LIKE TIMING MODEL
# ===========================================================================

class _HumanTiming:
    """Generates realistic keystroke timing based on biometric research.

    Models genuine human typing characteristics:
    - Digraph-aware timing (common pairs like 'th','er' are faster)
    - Code-specific patterns (slower for brackets, operators, special chars)
    - Burst/pause rhythm (5-18 chars fast, then micro-pause for thinking)
    - Word-boundary pauses (after spaces, at start of new tokens)
    - Cognitive pauses at code structure points (after {, before }, etc.)
    - Gradual fatigue with recovery micro-breaks
    - Hand-alternation speed bonus (keys on different hands are faster)
    """

    # Keys typed by left hand (QWERTY layout)
    _LEFT_HAND = frozenset('qwertasdfgzxcvb12345`~!@#$%')
    # Keys typed by right hand
    _RIGHT_HAND = frozenset('yuiophjklnm67890-=[]\\;\',./^&*()_+{}|:\"<>?')

    # Common digraphs typed fast (muscle memory)
    _FAST_PAIRS = frozenset({
        ('t', 'h'), ('h', 'e'), ('i', 'n'), ('a', 'n'), ('e', 'r'),
        ('r', 'e'), ('o', 'n'), ('n', 'd'), ('e', 'd'), ('i', 's'),
        ('o', 'u'), ('e', 'n'), ('i', 't'), ('s', 't'), ('a', 't'),
        ('h', 'a'), ('n', 'g'), ('l', 'e'), ('i', 'o'), ('o', 'r'),
        ('r', 'i'), ('t', 'i'), ('e', 's'), ('a', 'r'), ('n', 't'),
        ('a', 'l'), ('t', 'e'), ('s', 'e'), ('o', 'f'), ('d', 'e'),
        ('i', 'f'), ('e', 'l'), ('r', 'n'), ('f', 'o'), ('u', 'r'),
        ('l', 'l'), ('s', 's'), ('t', 'o'), ('c', 'o'), ('n', 'e'),
        # Code-specific fast pairs
        ('r', 'e'), ('t', 'u'), ('u', 'r'), ('n', ' '), ('i', 'n'),
        ('n', 't'), ('v', 'o'), ('o', 'i'), ('i', 'd'), ('c', 'l'),
        ('l', 'a'), ('a', 's'), ('s', 's'), ('f', 'o'), ('o', 'r'),
        ('w', 'h'), ('h', 'i'), ('i', 'l'), ('l', 'e'),
    })

    # Uncommon pairs typed slower (awkward finger positions)
    _SLOW_PAIRS = frozenset({
        ('z', 'q'), ('x', 'z'), ('p', 'q'), ('q', 'z'), ('j', 'x'),
        ('z', 'x'), ('q', 'j'), ('v', 'b'), ('b', 'v'), ('z', 'p'),
        ('m', 'n'), ('n', 'b'), ('b', 'n'), ('x', 'c'), ('c', 'x'),
    })

    # Characters that trigger cognitive pauses (thinking about what comes next)
    _THINK_BEFORE = frozenset('{([<')
    _THINK_AFTER = frozenset('})]>;')

    def __init__(self, base_interval=0.03):
        self.base_interval = base_interval

        # Dwell time: how long key is held (keyDown -> keyUp)
        self.dwell_mean = 0.078
        self.dwell_std = 0.024
        self.dwell_min = 0.038
        self.dwell_max = 0.165

        # Flight time: gap between keyUp and next keyDown
        self.flight_mean = max(0.022, base_interval - self.dwell_mean * 0.5)
        self.flight_std = 0.028
        self.flight_min = 0.012
        self.flight_max = 0.450

        # Burst/pause state
        self._chars_typed = 0
        self._burst_len = 0
        self._next_burst_pause = random.randint(5, 18)
        self._prev_char = None
        self._session_chars = 0
        self._last_pause_at = 0

    def get_dwell(self, ch):
        """How long to hold this key down (keyDown -> keyUp)."""
        mean = self.dwell_mean
        std = self.dwell_std

        if ch == ' ':
            mean *= 1.15       # spacebar thumb press slightly longer
        elif ch in '.,;:':
            mean *= 1.10       # punctuation slightly longer
        elif ch in '!?':
            mean *= 1.18       # sentence-ending marks more deliberate
        elif ch in '(){}[]<>':
            mean *= 1.20       # brackets: careful placement
        elif ch in '+-*/%=&|^~':
            mean *= 1.12       # operators: moderate
        elif ch.isupper():
            mean *= 1.06       # shift held = slightly longer
        elif ch in '0123456789':
            mean *= 1.04       # number row slightly slower
        elif ch == '\t':
            mean *= 0.90       # tab is a quick thumb press

        # Add slight random asymmetry (real humans have this)
        d = random.gauss(mean, std)
        # Occasional very slightly long press (1 in 30 chars)
        if random.random() < 0.033:
            d *= random.uniform(1.15, 1.4)
        return max(self.dwell_min, min(self.dwell_max, d))

    def get_flight(self, prev_ch, next_ch):
        """Gap between releasing prev_ch and pressing next_ch."""
        mean = self.flight_mean
        std = self.flight_std

        if prev_ch and next_ch:
            pl = prev_ch.lower()
            nl = next_ch.lower()
            pair = (pl, nl)

            # ── Digraph speed ──
            if pair in self._FAST_PAIRS:
                mean *= 0.68
                std *= 0.60
            elif pair in self._SLOW_PAIRS:
                mean *= 1.40
                std *= 1.20

            # ── Hand alternation bonus ──
            # Keys on different hands are typed faster (parallel movement)
            if pl in self._LEFT_HAND and nl in self._RIGHT_HAND:
                mean *= 0.82
            elif pl in self._RIGHT_HAND and nl in self._LEFT_HAND:
                mean *= 0.82
            # Same finger (approximate: same key column) is slower
            elif pl == nl:
                mean *= 1.25  # double letters

            # ── Same key repeat ──
            if prev_ch == next_ch:
                mean *= 1.15

        # ── Code structure cognitive pauses ──
        if next_ch and next_ch in self._THINK_BEFORE:
            # Thinking before opening bracket/paren
            mean += random.uniform(0.03, 0.10)
        if prev_ch and prev_ch in self._THINK_AFTER:
            # Brief pause after closing bracket/semicolon
            mean += random.uniform(0.02, 0.08)

        # ── Word boundary pause ──
        if prev_ch == ' ':
            mean *= random.uniform(1.05, 1.20)
        # After newline (thinking about new line content)
        if prev_ch == '\n':
            mean *= random.uniform(1.10, 1.35)

        # ── Sentence/statement boundary ──
        if prev_ch and prev_ch in '.!?;':
            mean *= random.uniform(1.25, 1.90)

        # ── Special char → letter transition (looking at keyboard) ──
        if prev_ch and prev_ch in '{}()[]<>+-*/=&|' and next_ch and next_ch.isalpha():
            mean *= random.uniform(1.05, 1.20)

        # ── Burst/pause pattern ──
        self._burst_len += 1
        if self._burst_len >= self._next_burst_pause:
            self._burst_len = 0
            self._next_burst_pause = random.randint(5, 18)
            # Micro-pause: thinking about next few characters
            mean += random.uniform(0.04, 0.18)

        # ── Fatigue with micro-recovery ──
        self._chars_typed += 1
        self._session_chars += 1
        if self._chars_typed > 200:
            fatigue = min(0.12, (self._chars_typed - 200) * 0.00012)
            mean += fatigue
            # Occasional micro-recovery (like shifting in chair)
            if self._chars_typed - self._last_pause_at > 150:
                if random.random() < 0.08:
                    mean += random.uniform(0.15, 0.40)
                    self._last_pause_at = self._chars_typed
                    # Partial fatigue reset after break
                    self._chars_typed = max(200, self._chars_typed - 80)

        f = random.gauss(mean, std)
        return max(self.flight_min, min(self.flight_max, f))

    def reset(self):
        """Reset timing state for a new typing session."""
        self._chars_typed = 0
        self._burst_len = 0
        self._next_burst_pause = random.randint(5, 18)
        self._session_chars = 0
        self._last_pause_at = 0


# ===========================================================================
# CORE COMPUTER CLASS
# ===========================================================================

# Global safety and speed settings
pyautogui.PAUSE = 0
pyautogui.FAILSAFE = True

# Regex patterns to detect code structure for human-like pacing
_BLOCK_OPENER = re.compile(r"[:{(\[]\s*$")
_NEW_STATEMENT = re.compile(
    r"^\s*(def|class|function|if|for|while|try|else|elif|except|finally)\b"
)


class Computer:
    """
    Handles screen capturing and code-aware typing for the AI agent.
    Designed for remote desktops where clipboard paste is disabled.

    Uses Windows SendInput for proper keyDown/keyUp events with
    realistic dwell and flight times to produce natural typing patterns.
    """

    # Characters that most code editors auto-close with a matching pair
    _AUTO_CLOSE_OPENERS = set('{([')

    def __init__(
        self,
        base_interval=0.03,
        jitter=0.01,
        newline_extra_delay=0.15,
        tab_extra_delay=0.08,
        block_open_pause=0.12,
        new_statement_pause=0.10,
        blank_line_pause=0.08,
        chunk_size=40,
        chunk_pause=0.25,
        dismiss_suggestions=True,
        fix_auto_indent=True,
        fix_auto_close=True,
    ):
        self.base_interval = base_interval
        self.jitter = jitter
        self.newline_extra_delay = newline_extra_delay
        self.tab_extra_delay = tab_extra_delay
        self.block_open_pause = block_open_pause
        self.new_statement_pause = new_statement_pause
        self.blank_line_pause = blank_line_pause
        self.chunk_size = chunk_size
        self.chunk_pause = chunk_pause
        self.dismiss_suggestions = dismiss_suggestions
        self.fix_auto_indent = fix_auto_indent
        self.fix_auto_close = fix_auto_close

        # Human timing model
        self.timing = _HumanTiming(base_interval=base_interval)

        # State management
        self._paused = False
        self._stop = False
        self._char_count = 0
        self._prev_ch = None

    # -----------------------------------------------------------------------
    # Vision Capabilities (DWMShield v3 — Stealth-First)
    # -----------------------------------------------------------------------

    def capture_desktop(self, force=False):
        """Stealth-first screen capture for the AI to analyze.

        Pipeline:
          1. Try syscall capture via thirdeye.dll (zero footprint, ignores WDA)
          2. If no WDA-protected windows → safe GDI BitBlt
          3. If WDA windows exist → abort (stealth compromised)

        Args:
            force: If True, capture even if stealth is compromised.

        Returns:
            Tuple of (png_bytes, mime_type)

        Raises:
            stealth_capture.StealthAbort: If stealth is compromised and force=False
        """
        from .stealth_capture import capture_desktop_stealth

        return capture_desktop_stealth(force=force)

    @staticmethod
    def move_to_position(x_percent, y_percent):
        """Move mouse cursor to a screen position given as 0-1 percentages.

        Uses Bézier curve movement with human-like speed variation,
        micro-jitter, and slight overshoot to look natural.
        """
        import time as _time
        pyautogui.FAILSAFE = False

        screen_w, screen_h = pyautogui.size()
        target_x = max(0, min(int(x_percent * screen_w), screen_w - 1))
        target_y = max(0, min(int(y_percent * screen_h), screen_h - 1))

        # Current position
        start_x, start_y = pyautogui.position()
        dist = math.hypot(target_x - start_x, target_y - start_y)

        if dist < 5:
            return  # Already there

        # ── Bézier control points (2 random control points for S-curve) ──
        # Offset control points perpendicular to the line for a curved path
        dx = target_x - start_x
        dy = target_y - start_y
        perp_x, perp_y = -dy, dx  # Perpendicular vector
        perp_len = math.hypot(perp_x, perp_y) or 1
        perp_x /= perp_len
        perp_y /= perp_len

        # Random curve intensity (bigger for longer distances)
        curve = random.uniform(0.1, 0.35) * dist
        drift1 = random.uniform(-curve, curve)
        drift2 = random.uniform(-curve * 0.5, curve * 0.5)

        cp1_x = start_x + dx * 0.3 + perp_x * drift1
        cp1_y = start_y + dy * 0.3 + perp_y * drift1
        cp2_x = start_x + dx * 0.7 + perp_x * drift2
        cp2_y = start_y + dy * 0.7 + perp_y * drift2

        # Slight overshoot target
        overshoot = random.uniform(3, 12)
        overshoot_x = target_x + (dx / (dist or 1)) * overshoot
        overshoot_y = target_y + (dy / (dist or 1)) * overshoot

        # ── Generate points along cubic Bézier ──
        # More steps for longer distances (feels natural)
        n_steps = max(25, min(80, int(dist / 8)))

        def bezier(t, p0, p1, p2, p3):
            u = 1 - t
            return u**3 * p0 + 3 * u**2 * t * p1 + 3 * u * t**2 * p2 + t**3 * p3

        # ── Move along the curve with variable speed ──
        # Ease-in-out: slow start, fast middle, slow end
        total_time = random.uniform(0.6, 1.4)  # Total move duration

        for i in range(1, n_steps + 1):
            # Ease-in-out parametric t
            raw_t = i / n_steps
            # Sinusoidal easing for natural acceleration
            t = 0.5 * (1 - math.cos(math.pi * raw_t))

            bx = bezier(t, start_x, cp1_x, cp2_x, overshoot_x)
            by = bezier(t, start_y, cp1_y, cp2_y, overshoot_y)

            # Add micro-jitter (±1-2 pixels, decreasing near target)
            jit = max(0, 2 * (1 - raw_t))
            bx += random.uniform(-jit, jit)
            by += random.uniform(-jit, jit)

            # Clamp to screen
            bx = max(0, min(int(bx), screen_w - 1))
            by = max(0, min(int(by), screen_h - 1))

            pyautogui.moveTo(bx, by, _pause=False)

            # Variable sleep (slow at start/end, fast in middle)
            step_time = total_time / n_steps
            if raw_t < 0.15 or raw_t > 0.85:
                step_time *= random.uniform(1.5, 2.5)  # Slower at edges
            else:
                step_time *= random.uniform(0.5, 1.0)  # Faster in middle
            _time.sleep(step_time)

        # ── Correction: move from overshoot to exact target ──
        # Small quick correction like a human adjusting
        _time.sleep(random.uniform(0.05, 0.15))
        cx, cy = pyautogui.position()
        correction_steps = random.randint(3, 6)
        for j in range(1, correction_steps + 1):
            frac = j / correction_steps
            mx = int(cx + (target_x - cx) * frac)
            my = int(cy + (target_y - cy) * frac)
            pyautogui.moveTo(mx, my, _pause=False)
            _time.sleep(random.uniform(0.01, 0.03))

    @staticmethod
    def wpm_to_interval(wpm: float) -> float:
        """Convert words-per-minute to per-character delay (seconds).

        Average word = 5 characters, so chars/sec = wpm * 5 / 60.
        """
        if wpm <= 0:
            return 0.03
        return 60.0 / (wpm * 5.0)

    # -----------------------------------------------------------------------
    # Typing Capabilities
    # -----------------------------------------------------------------------

    @property
    def is_paused(self):
        return self._paused

    def _dismiss_popup(self):
        """Dismiss autocomplete/suggestion popups without sending ESC.

        ESC would trigger keyboard.wait('esc') in main.py and exit the
        program.  Instead, press Right→Left (cursor stays put but most
        code editors close their autocomplete overlay).
        """
        if self.dismiss_suggestions:
            if _USE_INTERCEPTION:
                _icp.press("right")
                time.sleep(0.005)
                _icp.press("left")
            else:
                _press_key(0x27)   # VK_RIGHT
                time.sleep(0.005)
                _press_key(0x25)   # VK_LEFT
            time.sleep(0.005)

    def _wait_if_needed(self):
        while self._paused and not self._stop:
            time.sleep(0.05)
        return self._stop

    def _send_key_combo(self, modifier, key):
        """Send a key combo like Ctrl+A using Interception (or SendInput fallback).
        modifier: 'ctrl', 'shift', 'alt'
        key: single char like 'a', 'c', 'v'
        """
        mod_scan = {'ctrl': 0x1D, 'shift': 0x2A, 'alt': 0x38}.get(modifier, 0x1D)
        if _USE_INTERCEPTION and _icp_ctx:
            # Get scan code for the key
            info = _icp_get_key_info(key)
            if info:
                scan = info.scan_code
                # Modifier down
                _icp_ctx.send(_icp_ctx.keyboard, _IcpKeyStroke(mod_scan, _ICP_KEY_DOWN))
                time.sleep(0.008)
                # Key down + up
                _icp_ctx.send(_icp_ctx.keyboard, _IcpKeyStroke(scan, _ICP_KEY_DOWN))
                time.sleep(0.008)
                _icp_ctx.send(_icp_ctx.keyboard, _IcpKeyStroke(scan, _ICP_KEY_UP))
                time.sleep(0.008)
                # Modifier up
                _icp_ctx.send(_icp_ctx.keyboard, _IcpKeyStroke(mod_scan, _ICP_KEY_UP))
                time.sleep(0.01)
                return
        # Fallback: SendInput
        mod_vk = {'ctrl': 0x11, 'shift': 0x10, 'alt': 0x12}.get(modifier, 0x11)
        key_vk = ord(key.upper())
        mod_sc = _MapVirtualKeyW(mod_vk, _MAPVK_VK_TO_VSC)
        key_sc = _MapVirtualKeyW(key_vk, _MAPVK_VK_TO_VSC)
        _send_key(mod_vk, mod_sc, False)  # modifier down
        time.sleep(0.008)
        _send_key(key_vk, key_sc, False)  # key down
        time.sleep(0.008)
        _send_key(key_vk, key_sc, True)   # key up
        time.sleep(0.008)
        _send_key(mod_vk, mod_sc, True)   # modifier up

    def _type_char(self, ch):
        """Type a single character with realistic keyDown → dwell → keyUp.

        Uses Interception driver (kernel-level) when available — events
        appear identical to a real physical keyboard:
          ✅ No LLKHF_INJECTED flag
          ✅ Real hDevice handle
          ✅ Proper hardware scan codes
        Falls back to SendInput with VK+scan codes otherwise.
        """
        if ch == "\t":
            self._dismiss_popup()
            if _USE_INTERCEPTION:
                _icp.press("tab")
            else:
                _press_key(VK_TAB)
            self._char_count += 1
            return

        dwell = self.timing.get_dwell(ch)

        if _USE_INTERCEPTION:
            # ── RAW INTERCEPTION: bypass library's key_down/key_up ──
            # The library's _send_with_mods flickers Shift on/off per call,
            # garbling shifted characters.  Send raw KeyStrokes directly.
            try:
                data = _icp_get_key_info(ch)
                ctx = _icp_ctx

                # Press Shift if needed (fresh object each time — send may mutate it)
                if data.shift:
                    ctx.send(ctx.keyboard, _IcpKeyStroke(0x2A, _ICP_KEY_DOWN))
                    time.sleep(0.008)

                # Key down
                stroke_dn = _IcpKeyStroke(data.scan_code, _ICP_KEY_DOWN)
                if data.is_extended:
                    stroke_dn.flags |= _ICP_KEY_E0
                ctx.send(ctx.keyboard, stroke_dn)

                # Dwell (how long key is held)
                time.sleep(dwell)

                # Key up
                stroke_up = _IcpKeyStroke(data.scan_code, _ICP_KEY_UP)
                if data.is_extended:
                    stroke_up.flags |= _ICP_KEY_E0
                ctx.send(ctx.keyboard, stroke_up)

                # Release Shift if needed
                if data.shift:
                    time.sleep(0.008)
                    ctx.send(ctx.keyboard, _IcpKeyStroke(0x2A, _ICP_KEY_UP))
            except Exception:
                self._type_char_sendinput(ch, dwell)
        else:
            self._type_char_sendinput(ch, dwell)

        # Handle auto-close brackets
        if self.fix_auto_close and ch in self._AUTO_CLOSE_OPENERS:
            time.sleep(0.02)
            if _USE_INTERCEPTION:
                _icp.press("delete")
            else:
                _press_key(VK_DELETE)

        self._char_count += 1
        self._prev_ch = ch

    def _type_char_sendinput(self, ch, dwell):
        """SendInput fallback for _type_char (proper VK + scan codes)."""
        vk_scan = _VkKeyScanW(ch)
        if vk_scan == -1 or vk_scan == 0xFFFF:
            pyautogui.write(ch)
            return

        vk   = vk_scan & 0xFF
        mods = (vk_scan >> 8) & 0xFF
        need_shift = bool(mods & 1)
        need_ctrl  = bool(mods & 2)
        scan = _MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC)
        shift_scan = _MapVirtualKeyW(VK_LSHIFT, _MAPVK_VK_TO_VSC)

        if need_ctrl:
            _send_key(VK_CONTROL, _MapVirtualKeyW(VK_CONTROL, _MAPVK_VK_TO_VSC), False)
        if need_shift:
            _send_key(VK_LSHIFT, shift_scan, False)
        _send_key(vk, scan, False)
        time.sleep(dwell)
        _send_key(vk, scan, True)
        if need_shift:
            _send_key(VK_LSHIFT, shift_scan, True)
        if need_ctrl:
            _send_key(VK_CONTROL, _MapVirtualKeyW(VK_CONTROL, _MAPVK_VK_TO_VSC), True)

    def _new_line(self, prev_line, next_line):
        """Press Enter, then neutralize whatever auto-indent the editor
        adds so the next line starts with exactly the whitespace we want.

        Uses Shift+Home (proven approach from v8) which selects backwards
        from cursor to column 0 — works in ALL editors including Monaco,
        VS Code, LeetCode, etc.
        """
        # NOTE: No _dismiss_popup() here — Enter dismisses popups naturally.
        # Right→Left at EOL would move cursor before the last char, causing
        # the last character (like > in <vector> or : in public:) to be
        # split onto the next line and then deleted by Shift+Home.
        if _USE_INTERCEPTION:
            _icp.press("enter")
        else:
            _press_key(VK_RETURN)

        # Human-like pause after Enter
        pause = random.uniform(0.12, 0.30)
        if not prev_line.strip():
            pause += random.uniform(0.04, 0.12)
        elif _BLOCK_OPENER.search(prev_line):
            pause += random.uniform(0.06, 0.18)
        if _NEW_STATEMENT.match(next_line):
            pause += random.uniform(0.04, 0.10)
        time.sleep(pause)

        if self.fix_auto_indent:
            leading = re.match(r"[ \t]*", next_line).group(0)

            if _USE_INTERCEPTION:
                _icp.key_down("shiftleft")
                time.sleep(0.01)
                _icp.press("home")
                time.sleep(0.01)
                _icp.key_up("shiftleft")
                time.sleep(0.02)

                if leading:
                    for wch in leading:
                        k = "tab" if wch == "\t" else "space"
                        _icp.key_down(k)
                        time.sleep(0.006)
                        _icp.key_up(k)
                        time.sleep(0.006)
                else:
                    _icp.press("delete")
            else:
                shift_scan = _MapVirtualKeyW(VK_LSHIFT, _MAPVK_VK_TO_VSC)
                home_scan  = _MapVirtualKeyW(VK_HOME, _MAPVK_VK_TO_VSC)
                _send_key(VK_LSHIFT, shift_scan, False)
                time.sleep(0.01)
                _send_key(VK_HOME, home_scan, False)
                time.sleep(0.008)
                _send_key(VK_HOME, home_scan, True)
                time.sleep(0.01)
                _send_key(VK_LSHIFT, shift_scan, True)
                time.sleep(0.02)

                if leading:
                    space_scan = _MapVirtualKeyW(VK_SPACE, _MAPVK_VK_TO_VSC)
                    tab_scan   = _MapVirtualKeyW(VK_TAB, _MAPVK_VK_TO_VSC)
                    for wch in leading:
                        wvk = VK_TAB if wch == "\t" else VK_SPACE
                        wsc = tab_scan if wch == "\t" else space_scan
                        _send_key(wvk, wsc, False)
                        time.sleep(0.006)
                        _send_key(wvk, wsc, True)
                        time.sleep(0.006)
                else:
                    _press_key(VK_DELETE)
            time.sleep(0.02)

    def type_at_current_cursor(self, text, existing_text=None):
        """Type `text` with realistic human-like keystroke dynamics.

        Timing model per character:
          [flight gap] → [keyDown] → [dwell hold] → [keyUp]

        This produces natural inter-keystroke intervals AND realistic
        key-hold durations that pass keystroke dynamics analysis.

        Indentation: _new_line() handles placing the correct leading
        whitespace, so each line's leading whitespace is stripped here
        (except line 0 which types as-is).

        If `existing_text` is provided, lines matching the editor's
        existing content are skipped (cursor advanced with Down arrow)
        instead of retyped.
        """
        self._stop = False
        self._paused = False
        self._char_count = 0
        self._prev_ch = None
        self.timing.reset()

        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")

        # ── Skip matching lines from existing editor code ──
        skip_lines = 0
        if existing_text:
            existing_text = existing_text.replace("\r\n", "\n").replace("\r", "\n")
            existing_lines = existing_text.split("\n")
            # Count matching lines from the top
            for i in range(min(len(lines), len(existing_lines))):
                if lines[i].rstrip() == existing_lines[i].rstrip():
                    skip_lines += 1
                else:
                    break

            if skip_lines > 0:
                print(f"  Skipping {skip_lines} matching lines (already in editor)...")
                for _ in range(skip_lines):
                    if self._stop:
                        break
                    # Press Down arrow to skip this line
                    if _USE_INTERCEPTION:
                        _icp.press("down")
                    else:
                        _press_key(0x28)  # VK_DOWN
                    time.sleep(random.uniform(0.04, 0.10))

                # Now select from cursor to end of document and delete
                # (removes any remaining existing code after the matching prefix)
                if skip_lines < len(existing_lines):
                    time.sleep(0.05)
                    if _USE_INTERCEPTION:
                        # Home first to ensure we're at start of line
                        _icp.press("home")
                        time.sleep(0.02)
                        # Ctrl+Shift+End to select to end of document
                        _icp.key_down("ctrl", 0)
                        _icp.key_down("shiftleft", 0)
                        time.sleep(0.01)
                        _icp.press("end")
                        time.sleep(0.01)
                        _icp.key_up("shiftleft", 0)
                        _icp.key_up("ctrl", 0)
                        time.sleep(0.02)
                        # Delete selection
                        _icp.press("delete")
                    else:
                        _press_key(VK_HOME)
                        time.sleep(0.02)
                        _send_key(VK_CONTROL, _MapVirtualKeyW(VK_CONTROL, _MAPVK_VK_TO_VSC), False)
                        _send_key(VK_LSHIFT, _MapVirtualKeyW(VK_LSHIFT, _MAPVK_VK_TO_VSC), False)
                        time.sleep(0.01)
                        _send_key(VK_END, _MapVirtualKeyW(VK_END, _MAPVK_VK_TO_VSC), False)
                        time.sleep(0.008)
                        _send_key(VK_END, _MapVirtualKeyW(VK_END, _MAPVK_VK_TO_VSC), True)
                        time.sleep(0.01)
                        _send_key(VK_LSHIFT, _MapVirtualKeyW(VK_LSHIFT, _MAPVK_VK_TO_VSC), True)
                        _send_key(VK_CONTROL, _MapVirtualKeyW(VK_CONTROL, _MAPVK_VK_TO_VSC), True)
                        time.sleep(0.02)
                        _press_key(VK_DELETE)
                    time.sleep(0.1)

        # ── Type remaining lines (after skipped prefix) ──
        remaining_lines = lines[skip_lines:]

        for line_i, line in enumerate(remaining_lines):
            actual_i = skip_lines + line_i  # index in the full solution

            if actual_i == 0 or (skip_lines > 0 and line_i == 0):
                # First line to type: type as-is (no leading strip)
                to_type = line
            else:
                leading_len = len(re.match(r"[ \t]*", line).group(0))
                to_type = line[leading_len:]

            for ch in to_type:
                if self._wait_if_needed():
                    self._stop = False
                    self._paused = False
                    print("\n[ABORTED] Auto-typing stopped.")
                    return

                flight = self.timing.get_flight(self._prev_ch, ch)
                time.sleep(flight)
                self._type_char(ch)

            # Newline between remaining lines
            if line_i < len(remaining_lines) - 1:
                if self._wait_if_needed():
                    self._stop = False
                    self._paused = False
                    print("\n[ABORTED] Auto-typing stopped.")
                    return
                self._new_line(prev_line=line, next_line=remaining_lines[line_i + 1])
                self._prev_ch = "\n"

        self._stop = False
        self._paused = False
        print("\n[DONE] Auto-typing complete.")

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop(self):
        self._stop = True
        self._paused = False




# ===========================================================================
# HACKER TYPER MODE
# ===========================================================================

class HackerTyperMode:
    """Wraps the Computer class to allow manual key-mashing to type code."""
    def __init__(self, computer_instance, source_text, chunk_amount=3, chunk_type='chars'):
        self.computer = computer_instance
        self.source_text = source_text
        self.chunk_amount = chunk_amount
        self.chunk_type = chunk_type

        self.armed = False
        self.paused = False
        self.action_generator = None

        self.trigger_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

        self.intercept_keys = list(string.ascii_lowercase + string.digits + " -=+[]\\;',./`")
        self.intercept_keys.extend(['space', 'enter', 'backspace'])
        self.hooked_callbacks = []

    def _build_generator(self):
        text = self.source_text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")

        for line_i, line in enumerate(lines):
            # Yield ALL characters including leading whitespace
            for ch in line:
                yield ('char', ch)

            if line_i < len(lines) - 1:
                yield ('newline', (line, lines[line_i + 1]))

    def _hook_keys(self):
        if self.hooked_callbacks: return
        for k in self.intercept_keys:
            try:
                cb = keyboard.on_press_key(k, self._on_mash, suppress=True)
                self.hooked_callbacks.append(cb)
            except ValueError:
                pass

    def _unhook_keys(self):
        for cb in self.hooked_callbacks:
            keyboard.unhook_key(cb)
        self.hooked_callbacks.clear()

    def _on_mash(self, event):
        self.trigger_queue.put(1)

    def start_or_restart(self):
        self.abort(silent=True)
        self.armed = True
        self.paused = False
        self.action_generator = self._build_generator()
        self.trigger_queue.queue.clear()

        # Reset the core computer state just in case
        self.computer.stop()
        self.computer._stop = False
        self.computer._paused = False

        self._hook_keys()
        print("\n[HACKER MODE ARMED] Start mashing your keyboard! Every keypress writes code.")

    def abort(self, silent=False):
        if self.armed or self.paused:
            self.armed = False
            self.paused = False
            self._unhook_keys()
            self.trigger_queue.queue.clear()
            if not silent:
                print("\n[HACKER MODE ABORTED] Normal typing restored.")

    def toggle_pause(self):
        if not self.armed:
            return
        self.paused = not self.paused
        if self.paused:
            self._unhook_keys()
            print("\n[HACKER MODE PAUSED] Normal typing restored. Press Alt+3 to resume.")
        else:
            self._hook_keys()
            print("\n[HACKER MODE RESUMED] Keep mashing keys to write code.")

    def _worker_loop(self):
        while True:
            self.trigger_queue.get()
            if not self.armed or self.paused:
                continue
            try:
                self._output_chunk()
            except StopIteration:
                print("\n[DONE] Code complete. Disarming.")
                self.abort(silent=True)

    def _output_chunk(self):
        if self.chunk_type == 'chars':
            for _ in range(self.chunk_amount):
                action, data = next(self.action_generator)
                self._execute_action(action, data)
        elif self.chunk_type == 'words':
            words_done = 0
            while words_done < self.chunk_amount:
                action, data = next(self.action_generator)
                self._execute_action(action, data)
                if action == 'char' and data in (' ', '\t'):
                    words_done += 1
                elif action == 'newline':
                    words_done += 1
        elif self.chunk_type == 'lines':
            lines_done = 0
            while lines_done < self.chunk_amount:
                action, data = next(self.action_generator)
                self._execute_action(action, data)
                if action == 'newline':
                    lines_done += 1

    def _execute_action(self, action, data):
        if action == 'char':
            # Flight time only — dwell is handled inside _type_char now
            flight = self.computer.timing.get_flight(self.computer._prev_ch, data)
            time.sleep(flight * 0.4)  # faster in hacker mode
            self.computer._type_char(data)
        elif action == 'newline':
            self.computer._new_line(data[0], data[1])


# ===========================================================================
# MAIN EXECUTION & HOTKEYS
# ===========================================================================
if __name__ == "__main__":
    computer = Computer()
    hacker_mode = HackerTyperMode(computer, SOURCE_TEXT, CHUNK_AMOUNT, CHUNK_TYPE)

    def trigger_auto_mode():
        """F1: Writes all the code automatically."""
        hacker_mode.abort(silent=True) # Turn off hacker mode if it's on
        print("\n[AUTO MODE] Starting automatic typing...")
        # Run in a thread so the F3/F4 hotkeys aren't blocked while it types
        threading.Thread(target=computer.type_at_current_cursor, args=(SOURCE_TEXT,), daemon=True).start()

    def universal_pause():
        """F3: Pauses whichever mode is currently active."""
        if hacker_mode.armed:
            hacker_mode.toggle_pause()
        else:
            if computer.is_paused:
                computer.resume()
                print("\n[AUTO MODE RESUMED]")
            else:
                computer.pause()
                print("\n[AUTO MODE PAUSED] Press F3 again to resume.")

    def universal_abort():
        """F4: Stops both modes immediately."""
        computer.stop()
        hacker_mode.abort()

    # Bind the specific hotkeys you requested
    keyboard.add_hotkey("f1", trigger_auto_mode)
    keyboard.add_hotkey("f2", hacker_mode.start_or_restart)
    keyboard.add_hotkey("f3", universal_pause)
    keyboard.add_hotkey("f4", universal_abort)

    print("="*65)
    print("Desktop Computer Agent Ready.")
    print("="*65)
    print("F1 = AUTO MODE   : Automatically type the whole code in one go.")
    print("F2 = HACKER MODE : Arm keyboard. Mash keys to type code manually.")
    print("F3 = PAUSE       : Pause either mode so you can type normally.")
    print("F4 = ABORT       : Stop entirely.")
    print("="*65)

    keyboard.wait()