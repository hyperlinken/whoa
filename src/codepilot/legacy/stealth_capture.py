"""DWMShield v4 — Robust Screen Capture (multiple fallback methods).

Capture pipeline (tries each until one returns non-blank data):
  1. Syscall capture via thirdeye.dll (zero footprint, ignores WDA)
  2. DXGI Desktop Duplication via dxcam (driver-level, bypasses WDA)
  3. PrintScreen + clipboard (uses Windows' own screenshot mechanism)
  4. GDI BitBlt with CAPTUREBLT flag (captures layered windows)
  5. GDI BitBlt standard (basic fallback)

All win32 calls use ctypes — no Rust/C build required at runtime.
"""

import ctypes
import ctypes.wintypes
import io
import logging
import os
import sys
import struct
import time
from enum import IntEnum
from typing import Optional, Tuple

_log = logging.getLogger("cpdbg")

# ═══════════════════════════════════════════════════════════════════════════
# WDA DETECTION  (ctypes → user32.dll)
# ═══════════════════════════════════════════════════════════════════════════

_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32

# Constants
WDA_NONE = 0x00000000
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
BI_RGB = 0
VK_SNAPSHOT = 0x2C
KEYEVENTF_KEYUP = 0x0002
CF_DIB = 8
CF_BITMAP = 2

# Callback type for EnumWindows
WNDENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.BOOL,
    ctypes.wintypes.HWND,
    ctypes.wintypes.LPARAM,
)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", ctypes.wintypes.DWORD * 3),
    ]


class ProtectedWindow:
    """A window with WDA protection active."""

    def __init__(self, hwnd: int, pid: int, title: str, affinity: int):
        self.hwnd = hwnd
        self.pid = pid
        self.title = title
        self.affinity = affinity

    def affinity_name(self) -> str:
        return {0x01: "WDA_MONITOR", 0x11: "WDA_EXCLUDEFROMCAPTURE"}.get(
            self.affinity, f"UNKNOWN(0x{self.affinity:02X})"
        )


def find_protected_windows() -> list:
    """Enumerate all visible windows and return those with WDA protection."""
    results = []

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        affinity = ctypes.wintypes.DWORD(0)
        rc = _user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity))
        if rc == 0:
            return True  # can't query, skip
        if affinity.value != WDA_NONE:
            pid = ctypes.wintypes.DWORD(0)
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            buf = ctypes.create_unicode_buffer(256)
            length = _user32.GetWindowTextW(hwnd, buf, 256)
            title = buf.value[:length]
            results.append(ProtectedWindow(hwnd, pid.value, title, affinity.value))
        return True

    _user32.EnumWindows(callback, 0)
    return results


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION — check if captured image is non-blank
# ═══════════════════════════════════════════════════════════════════════════

def _is_blank_image(png_bytes: bytes, threshold: int = 10000) -> bool:
    """Check if PNG is essentially blank (all white/black/uniform).

    A real screenshot of 1920x1080 desktop is typically 200KB-2MB.
    A blank 1920x1080 PNG compresses to ~5-10KB.
    """
    if len(png_bytes) < threshold:
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# METHOD 1: THIRDEYE.DLL SYSCALL CAPTURE  (stealth — zero footprint)
# ═══════════════════════════════════════════════════════════════════════════

class ThirdeyeFormat(IntEnum):
    JPEG = 0
    PNG = 1
    BMP = 2


class ThirdeyeOptions(ctypes.Structure):
    _fields_ = [
        ("format", ctypes.c_int),
        ("quality", ctypes.c_int),
        ("bypassProtection", ctypes.c_int),
    ]


def _find_thirdeye_dll() -> Optional[str]:
    """Look for thirdeye.dll in common locations."""
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "thirdeye.dll"),
        os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "thirdeye.dll"),
        os.path.join(os.getcwd(), "thirdeye.dll"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _capture_syscall(dll_path: str) -> bytes:
    """Capture screen via thirdeye.dll syscalls. Returns PNG bytes."""
    lib = ctypes.WinDLL(dll_path)

    lib.Thirdeye_CreateContext.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    lib.Thirdeye_CreateContext.restype = ctypes.c_int
    lib.Thirdeye_DestroyContext.argtypes = [ctypes.c_void_p]
    lib.Thirdeye_DestroyContext.restype = None
    lib.Thirdeye_CaptureToBuffer.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ThirdeyeOptions),
    ]
    lib.Thirdeye_CaptureToBuffer.restype = ctypes.c_int
    lib.Thirdeye_FreeBuffer.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
    lib.Thirdeye_FreeBuffer.restype = None
    lib.Thirdeye_GetLastError.argtypes = [ctypes.c_void_p]
    lib.Thirdeye_GetLastError.restype = ctypes.c_char_p

    ctx = ctypes.c_void_p()
    rc = lib.Thirdeye_CreateContext(ctypes.byref(ctx))
    if rc != 0 or not ctx:
        raise RuntimeError(f"Thirdeye_CreateContext failed (rc={rc})")

    try:
        opts = ThirdeyeOptions()
        opts.format = int(ThirdeyeFormat.PNG)
        opts.quality = 100
        opts.bypassProtection = 1

        buf = ctypes.POINTER(ctypes.c_uint8)()
        size = ctypes.c_uint32(0)
        rc = lib.Thirdeye_CaptureToBuffer(
            ctx, ctypes.byref(buf), ctypes.byref(size), ctypes.byref(opts)
        )
        if rc != 0 or not buf or size.value == 0:
            err = lib.Thirdeye_GetLastError(ctx)
            msg = err.decode("utf-8", "replace") if err else "unknown"
            raise RuntimeError(f"Thirdeye_CaptureToBuffer failed: {msg}")

        try:
            return ctypes.string_at(buf, size.value)
        finally:
            lib.Thirdeye_FreeBuffer(buf)
    finally:
        lib.Thirdeye_DestroyContext(ctx)


# ═══════════════════════════════════════════════════════════════════════════
# METHOD 2: DXGI DESKTOP DUPLICATION via dxcam (driver-level)
# ═══════════════════════════════════════════════════════════════════════════

def _capture_dxcam() -> bytes:
    """Capture via dxcam (DXGI Desktop Duplication). Returns PNG bytes."""
    import dxcam
    from PIL import Image

    camera = dxcam.create(output_color="BGR")
    frame = camera.grab()
    if frame is None:
        # First grab can return None, retry
        time.sleep(0.1)
        frame = camera.grab()
    del camera
    if frame is None:
        raise RuntimeError("dxcam returned None frame")

    img = Image.fromarray(frame[..., ::-1])  # BGR -> RGB
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════
# METHOD 3: PRINTSCREEN + CLIPBOARD  (Windows' own screenshot mechanism)
# ═══════════════════════════════════════════════════════════════════════════

def _capture_printscreen() -> bytes:
    """Press PrintScreen, read clipboard, return PNG bytes.

    Uses Windows' built-in screenshot mechanism — works even when
    other capture APIs are blocked by security software.
    """
    from PIL import Image

    # Clear clipboard first
    _user32.OpenClipboard(0)
    ctypes.windll.user32.EmptyClipboard()
    ctypes.windll.user32.CloseClipboard()

    # Press and release PrintScreen
    _user32.keybd_event(VK_SNAPSHOT, 0, 0, 0)
    _user32.keybd_event(VK_SNAPSHOT, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.5)  # Give Windows time to populate clipboard

    # Read clipboard using PIL
    from PIL import ImageGrab
    img = ImageGrab.grabclipboard()
    if img is None:
        # Retry with longer wait
        time.sleep(0.5)
        img = ImageGrab.grabclipboard()
    if img is None:
        raise RuntimeError("PrintScreen: clipboard empty after PrtSc")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════
# METHOD 4: GDI BITBLT + CAPTUREBLT  (captures layered windows)
# ═══════════════════════════════════════════════════════════════════════════

def _capture_gdi_captureblt() -> bytes:
    """Capture via GDI BitBlt with CAPTUREBLT flag. Returns PNG bytes.

    CAPTUREBLT captures layered/transparent windows that standard
    BitBlt might miss.
    """
    from PIL import Image

    width = _user32.GetSystemMetrics(SM_CXSCREEN)
    height = _user32.GetSystemMetrics(SM_CYSCREEN)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid screen dimensions: {width}x{height}")

    desktop_dc = _user32.GetDC(0)
    if not desktop_dc:
        raise RuntimeError("GetDC(desktop) failed")

    mem_dc = _gdi32.CreateCompatibleDC(desktop_dc)
    bitmap = _gdi32.CreateCompatibleBitmap(desktop_dc, width, height)
    old_obj = _gdi32.SelectObject(mem_dc, bitmap)

    try:
        # BitBlt with CAPTUREBLT
        _gdi32.BitBlt(mem_dc, 0, 0, width, height, desktop_dc, 0, 0,
                      SRCCOPY | CAPTUREBLT)

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB

        pixel_data = ctypes.create_string_buffer(width * height * 4)
        lines = _gdi32.GetDIBits(
            mem_dc, bitmap, 0, height, pixel_data,
            ctypes.byref(bmi), DIB_RGB_COLORS
        )
        if lines == 0:
            raise RuntimeError("GetDIBits returned 0 scanlines")

        raw = bytearray(pixel_data.raw)
        for i in range(0, len(raw), 4):
            raw[i], raw[i + 2] = raw[i + 2], raw[i]

        img = Image.frombytes("RGBA", (width, height), bytes(raw))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    finally:
        _gdi32.SelectObject(mem_dc, old_obj)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(0, desktop_dc)


# ═══════════════════════════════════════════════════════════════════════════
# METHOD 5: GDI BITBLT STANDARD  (basic fallback)
# ═══════════════════════════════════════════════════════════════════════════

def _capture_gdi() -> bytes:
    """Capture primary screen via GDI BitBlt. Returns PNG bytes."""
    from PIL import Image

    width = _user32.GetSystemMetrics(SM_CXSCREEN)
    height = _user32.GetSystemMetrics(SM_CYSCREEN)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid screen dimensions: {width}x{height}")

    desktop_dc = _user32.GetDC(0)
    if not desktop_dc:
        raise RuntimeError("GetDC(desktop) failed")

    mem_dc = _gdi32.CreateCompatibleDC(desktop_dc)
    bitmap = _gdi32.CreateCompatibleBitmap(desktop_dc, width, height)
    old_obj = _gdi32.SelectObject(mem_dc, bitmap)

    try:
        _gdi32.BitBlt(mem_dc, 0, 0, width, height, desktop_dc, 0, 0, SRCCOPY)

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB

        pixel_data = ctypes.create_string_buffer(width * height * 4)
        lines = _gdi32.GetDIBits(
            mem_dc, bitmap, 0, height, pixel_data,
            ctypes.byref(bmi), DIB_RGB_COLORS
        )
        if lines == 0:
            raise RuntimeError("GetDIBits returned 0 scanlines")

        raw = bytearray(pixel_data.raw)
        for i in range(0, len(raw), 4):
            raw[i], raw[i + 2] = raw[i + 2], raw[i]

        img = Image.frombytes("RGBA", (width, height), bytes(raw))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    finally:
        _gdi32.SelectObject(mem_dc, old_obj)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(0, desktop_dc)


# ═══════════════════════════════════════════════════════════════════════════
# METHOD 6: PIL ImageGrab (simple, uses GDI internally)
# ═══════════════════════════════════════════════════════════════════════════

def _capture_pil() -> bytes:
    """Capture via PIL ImageGrab.grab(). Returns PNG bytes."""
    from PIL import ImageGrab
    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════
# DXGI CAPTURE via DxgiCapture.dll  (C# DLL, legacy support)
# ═══════════════════════════════════════════════════════════════════════════

def _find_dxgi_dll() -> Optional[str]:
    """Look for DxgiCapture.dll."""
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "DxgiCapture.dll"),
        os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "DxgiCapture.dll"),
        os.path.join(os.getcwd(), "DxgiCapture.dll"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _capture_dxgi_subprocess() -> bytes:
    """Fallback: call DxgiCapture via a subprocess with .NET runtime."""
    import subprocess
    import base64

    dll_path = _find_dxgi_dll()
    if not dll_path:
        raise RuntimeError("DxgiCapture.dll not found")

    script = f'''
using System;
using System.Reflection;
class P {{
    static void Main() {{
        var asm = Assembly.LoadFrom(@"{dll_path}");
        var t = asm.GetType("DxgiCapture.ScreenCapture");
        var m = t.GetMethod("CaptureBestEffort");
        byte[] data = (byte[])m.Invoke(null, null);
        Console.Write(Convert.ToBase64String(data));
    }}
}}
'''
    script_path = os.path.join(os.path.dirname(dll_path), "_dxgi_cap.cs")
    exe_path = os.path.join(os.path.dirname(dll_path), "_dxgi_cap.exe")

    if not os.path.isfile(exe_path):
        with open(script_path, "w") as f:
            f.write(script)
        csc = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
        subprocess.run(
            [csc, "/out:" + exe_path, "/reference:" + dll_path,
             "/reference:System.Drawing.dll", script_path],
            capture_output=True, timeout=30
        )

    if not os.path.isfile(exe_path):
        raise RuntimeError("Failed to compile DXGI capture helper")

    result = subprocess.run(
        [exe_path], capture_output=True, timeout=15, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"DXGI capture failed: {result.stderr}")

    return base64.b64decode(result.stdout)


# ═══════════════════════════════════════════════════════════════════════════
# STEALTH-FIRST PIPELINE  (public API)
# ═══════════════════════════════════════════════════════════════════════════

class StealthAbort(Exception):
    """Raised when stealth capture is not possible."""

    def __init__(self, protected_windows: list):
        self.protected_windows = protected_windows
        titles = [w.title or f"HWND 0x{w.hwnd:X}" for w in protected_windows]
        shown = ", ".join(titles[:3])
        suffix = "..." if len(titles) > 3 else ""
        count = len(protected_windows)
        super().__init__(
            f"Stealth compromised: {count} WDA-protected window(s) detected "
            f"({shown}{suffix}). "
            f"Place thirdeye.dll next to the script for stealth capture."
        )


# Ordered capture methods: (name, function, description)
_CAPTURE_METHODS = [
    ("syscall",       None,                     "thirdeye.dll syscall"),
    ("dxcam",         "_capture_dxcam",          "DXGI Desktop Duplication"),
    ("printscreen",   "_capture_printscreen",    "PrintScreen + clipboard"),
    ("gdi_captureblt","_capture_gdi_captureblt", "GDI BitBlt + CAPTUREBLT"),
    ("gdi",           "_capture_gdi",            "GDI BitBlt standard"),
    ("pil",           "_capture_pil",            "PIL ImageGrab"),
    ("dxgi_dll",      None,                     "DxgiCapture.dll"),
]


def _try_capture(name: str, capture_fn, validate: bool = True) -> Optional[bytes]:
    """Try a single capture method, return PNG bytes or None."""
    try:
        data = capture_fn()
        if validate and _is_blank_image(data):
            _log.debug("CAPTURE [%s]: blank image (%d bytes), skipping", name, len(data))
            return None
        _log.debug("CAPTURE [%s]: OK, %d bytes", name, len(data))
        return data
    except Exception as e:
        _log.debug("CAPTURE [%s]: FAILED: %s", name, e)
        return None


def robust_capture() -> Tuple[bytes, str]:
    """Try ALL capture methods until one returns a non-blank image.

    Pipeline (in order):
      1. thirdeye.dll syscall (if available)
      2. dxcam DXGI (if installed)
      3. PrintScreen + clipboard
      4. GDI BitBlt + CAPTUREBLT
      5. GDI BitBlt standard
      6. PIL ImageGrab
      7. DxgiCapture.dll subprocess (if available)

    Returns:
        Tuple of (png_bytes, mime_type)

    Raises:
        RuntimeError: If ALL methods fail
    """
    _log.debug("CAPTURE: starting robust capture pipeline")

    # 1. Syscall (thirdeye.dll)
    dll_path = _find_thirdeye_dll()
    if dll_path:
        data = _try_capture("syscall", lambda: _capture_syscall(dll_path))
        if data:
            return (data, "image/png")

    # 2. dxcam DXGI
    try:
        import dxcam  # noqa: F401
        data = _try_capture("dxcam", _capture_dxcam)
        if data:
            return (data, "image/png")
    except ImportError:
        _log.debug("CAPTURE [dxcam]: not installed")

    # 3. PrintScreen + clipboard
    data = _try_capture("printscreen", _capture_printscreen)
    if data:
        return (data, "image/png")

    # 4. GDI + CAPTUREBLT
    data = _try_capture("gdi_captureblt", _capture_gdi_captureblt)
    if data:
        return (data, "image/png")

    # 5. GDI standard
    data = _try_capture("gdi", _capture_gdi, validate=False)
    if data:
        return (data, "image/png")

    # 6. PIL ImageGrab
    data = _try_capture("pil", _capture_pil)
    if data:
        return (data, "image/png")

    # 7. DxgiCapture.dll
    dxgi_dll = _find_dxgi_dll()
    if dxgi_dll:
        data = _try_capture("dxgi_dll", _capture_dxgi_subprocess)
        if data:
            return (data, "image/png")

    raise RuntimeError("ALL capture methods failed — no screenshot possible")


def stealth_capture() -> Tuple[bytes, str]:
    """Stealth-first screen capture. Returns (png_bytes, mime_type).

    Pipeline:
      1. Try syscall capture via thirdeye.dll (zero footprint)
      2. Check for WDA-protected windows
         - None found -> try robust capture pipeline
         - Found -> try DXGI/PrintScreen (bypass WDA)
         - All fail -> raise StealthAbort

    Returns:
        Tuple of (image_bytes, mime_type)

    Raises:
        StealthAbort: If stealth capture is not possible
        RuntimeError: If capture fails for technical reasons
    """
    # -- Step 1: Syscall capture (best stealth) --
    dll_path = _find_thirdeye_dll()
    if dll_path:
        data = _try_capture("syscall", lambda: _capture_syscall(dll_path))
        if data:
            return (data, "image/png")

    # -- Step 2: Check WDA --
    protected = find_protected_windows()

    if not protected:
        # No WDA windows -> try all methods
        return robust_capture()

    # -- Step 3: WDA detected -> try methods that bypass WDA --
    # dxcam (DXGI)
    try:
        import dxcam  # noqa: F401
        data = _try_capture("dxcam", _capture_dxcam)
        if data:
            return (data, "image/png")
    except ImportError:
        pass

    # PrintScreen
    data = _try_capture("printscreen", _capture_printscreen)
    if data:
        return (data, "image/png")

    # DxgiCapture.dll
    dxgi_dll = _find_dxgi_dll()
    if dxgi_dll:
        data = _try_capture("dxgi_dll", _capture_dxgi_subprocess)
        if data:
            return (data, "image/png")

    # -- Step 4: All stealth methods exhausted --
    raise StealthAbort(protected)


def force_capture() -> Tuple[bytes, str]:
    """Force capture using the best available method. NOT stealth.

    Tries ALL methods in order until one works.
    """
    return robust_capture()


def capture_desktop_stealth(force: bool = False) -> Tuple[bytes, str]:
    """Unified entry point for CodePilot.

    Args:
        force: If True, capture even if stealth is compromised.

    Returns:
        Tuple of (image_bytes, mime_type)

    Raises:
        StealthAbort: If stealth is compromised and force=False
    """
    if force:
        return force_capture()
    return stealth_capture()
