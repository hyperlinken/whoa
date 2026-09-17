"""DWMShield v4 — Stealth-First Screen Capture (Low-Level Only).

All capture methods use direct Win32 API via ctypes — no high-level
packages, no keyboard simulation, no third-party dependencies.

Pipeline:
  1. Syscall capture via thirdeye.dll  (zero footprint, ignores WDA)
  2. GDI BitBlt + CAPTUREBLT          (captures layered windows)
  3. GDI BitBlt standard              (basic fallback)
  4. DxgiCapture.dll subprocess        (if available)
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
# WIN32 CONSTANTS + STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════

_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32

WDA_NONE = 0x00000000
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
BI_RGB = 0

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


# ═══════════════════════════════════════════════════════════════════════════
# WDA DETECTION
# ═══════════════════════════════════════════════════════════════════════════

class ProtectedWindow:
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
    results = []

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        affinity = ctypes.wintypes.DWORD(0)
        rc = _user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity))
        if rc == 0:
            return True
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
# BLANK DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def _is_blank_image(png_bytes: bytes, threshold: int = 15000) -> bool:
    """Real 1920x1080 screenshot = 200KB-2MB. Blank = ~5-10KB."""
    return len(png_bytes) < threshold


def _raw_to_png(raw_bgra: bytearray, width: int, height: int) -> bytes:
    """Convert raw BGRA pixel data to PNG using PIL."""
    from PIL import Image
    # BGRA -> RGBA
    for i in range(0, len(raw_bgra), 4):
        raw_bgra[i], raw_bgra[i + 2] = raw_bgra[i + 2], raw_bgra[i]
    img = Image.frombytes("RGBA", (width, height), bytes(raw_bgra))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════
# METHOD 1: THIRDEYE.DLL SYSCALL (zero footprint, ignores WDA)
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
            ctx, ctypes.byref(buf), ctypes.byref(size), ctypes.byref(opts))
        if rc != 0 or not buf or size.value == 0:
            err = lib.Thirdeye_GetLastError(ctx)
            msg = err.decode("utf-8", "replace") if err else "unknown"
            raise RuntimeError(f"Thirdeye capture failed: {msg}")
        try:
            return ctypes.string_at(buf, size.value)
        finally:
            lib.Thirdeye_FreeBuffer(buf)
    finally:
        lib.Thirdeye_DestroyContext(ctx)


# ═══════════════════════════════════════════════════════════════════════════
# METHOD 2: GDI BitBlt + CAPTUREBLT  (captures layered/transparent windows)
# ═══════════════════════════════════════════════════════════════════════════

def _capture_gdi_captureblt() -> bytes:
    """GDI capture with CAPTUREBLT flag — captures layered windows."""
    width = _user32.GetSystemMetrics(SM_CXSCREEN)
    height = _user32.GetSystemMetrics(SM_CYSCREEN)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid screen: {width}x{height}")

    desktop_dc = _user32.GetDC(0)
    if not desktop_dc:
        raise RuntimeError("GetDC(0) failed")

    mem_dc = _gdi32.CreateCompatibleDC(desktop_dc)
    bitmap = _gdi32.CreateCompatibleBitmap(desktop_dc, width, height)
    old_obj = _gdi32.SelectObject(mem_dc, bitmap)
    try:
        _gdi32.BitBlt(mem_dc, 0, 0, width, height, desktop_dc, 0, 0,
                      SRCCOPY | CAPTUREBLT)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        pixels = ctypes.create_string_buffer(width * height * 4)
        lines = _gdi32.GetDIBits(mem_dc, bitmap, 0, height, pixels,
                                 ctypes.byref(bmi), DIB_RGB_COLORS)
        if lines == 0:
            raise RuntimeError("GetDIBits returned 0")
        return _raw_to_png(bytearray(pixels.raw), width, height)
    finally:
        _gdi32.SelectObject(mem_dc, old_obj)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(0, desktop_dc)


# ═══════════════════════════════════════════════════════════════════════════
# METHOD 3: GDI BitBlt STANDARD
# ═══════════════════════════════════════════════════════════════════════════

def _capture_gdi() -> bytes:
    """Standard GDI BitBlt capture."""
    width = _user32.GetSystemMetrics(SM_CXSCREEN)
    height = _user32.GetSystemMetrics(SM_CYSCREEN)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid screen: {width}x{height}")

    desktop_dc = _user32.GetDC(0)
    if not desktop_dc:
        raise RuntimeError("GetDC(0) failed")

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
        pixels = ctypes.create_string_buffer(width * height * 4)
        lines = _gdi32.GetDIBits(mem_dc, bitmap, 0, height, pixels,
                                 ctypes.byref(bmi), DIB_RGB_COLORS)
        if lines == 0:
            raise RuntimeError("GetDIBits returned 0")
        return _raw_to_png(bytearray(pixels.raw), width, height)
    finally:
        _gdi32.SelectObject(mem_dc, old_obj)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(0, desktop_dc)


# ═══════════════════════════════════════════════════════════════════════════
# METHOD 4: GDI Virtual Screen (multi-monitor)
# ═══════════════════════════════════════════════════════════════════════════

def _capture_gdi_virtual() -> bytes:
    """GDI capture of entire virtual screen (all monitors)."""
    x = _user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid virtual screen: {width}x{height}")

    desktop_dc = _user32.GetDC(0)
    if not desktop_dc:
        raise RuntimeError("GetDC(0) failed")

    mem_dc = _gdi32.CreateCompatibleDC(desktop_dc)
    bitmap = _gdi32.CreateCompatibleBitmap(desktop_dc, width, height)
    old_obj = _gdi32.SelectObject(mem_dc, bitmap)
    try:
        _gdi32.BitBlt(mem_dc, 0, 0, width, height, desktop_dc, x, y,
                      SRCCOPY | CAPTUREBLT)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        pixels = ctypes.create_string_buffer(width * height * 4)
        lines = _gdi32.GetDIBits(mem_dc, bitmap, 0, height, pixels,
                                 ctypes.byref(bmi), DIB_RGB_COLORS)
        if lines == 0:
            raise RuntimeError("GetDIBits returned 0")
        return _raw_to_png(bytearray(pixels.raw), width, height)
    finally:
        _gdi32.SelectObject(mem_dc, old_obj)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(0, desktop_dc)


# ═══════════════════════════════════════════════════════════════════════════
# METHOD 5: GDI CreateDC("DISPLAY") — bypasses some capture blocks
# ═══════════════════════════════════════════════════════════════════════════

def _capture_gdi_display_dc() -> bytes:
    """GDI capture using CreateDC('DISPLAY') instead of GetDC(0).

    CreateDC targets the display driver directly rather than the
    desktop window, which can bypass some security hooks.
    """
    width = _user32.GetSystemMetrics(SM_CXSCREEN)
    height = _user32.GetSystemMetrics(SM_CYSCREEN)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid screen: {width}x{height}")

    # CreateDC to the display driver directly
    display_dc = _gdi32.CreateDCW("DISPLAY", None, None, None)
    if not display_dc:
        raise RuntimeError("CreateDC('DISPLAY') failed")

    mem_dc = _gdi32.CreateCompatibleDC(display_dc)
    bitmap = _gdi32.CreateCompatibleBitmap(display_dc, width, height)
    old_obj = _gdi32.SelectObject(mem_dc, bitmap)
    try:
        _gdi32.BitBlt(mem_dc, 0, 0, width, height, display_dc, 0, 0,
                      SRCCOPY | CAPTUREBLT)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        pixels = ctypes.create_string_buffer(width * height * 4)
        lines = _gdi32.GetDIBits(mem_dc, bitmap, 0, height, pixels,
                                 ctypes.byref(bmi), DIB_RGB_COLORS)
        if lines == 0:
            raise RuntimeError("GetDIBits returned 0")
        return _raw_to_png(bytearray(pixels.raw), width, height)
    finally:
        _gdi32.SelectObject(mem_dc, old_obj)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(mem_dc)
        _gdi32.DeleteDC(display_dc)


# ═══════════════════════════════════════════════════════════════════════════
# METHOD 6: DxgiCapture.dll subprocess (if available)
# ═══════════════════════════════════════════════════════════════════════════

def _find_dxgi_dll() -> Optional[str]:
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
# CAPTURE PIPELINE  (public API)
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


def _try_capture(name: str, fn, validate: bool = True) -> Optional[bytes]:
    """Try a capture method. Returns PNG bytes or None."""
    try:
        data = fn()
        if validate and _is_blank_image(data):
            _log.debug("CAPTURE [%s]: blank (%d bytes), skip", name, len(data))
            return None
        _log.debug("CAPTURE [%s]: OK %d bytes", name, len(data))
        return data
    except Exception as e:
        _log.debug("CAPTURE [%s]: FAIL: %s", name, e)
        return None


def robust_capture() -> Tuple[bytes, str]:
    """Try all low-level capture methods until one returns real content.

    Pipeline:
      1. thirdeye.dll syscall
      2. GDI CreateDC("DISPLAY") + CAPTUREBLT
      3. GDI BitBlt + CAPTUREBLT
      4. GDI Virtual Screen
      5. GDI BitBlt standard
      6. DxgiCapture.dll subprocess
    """
    _log.debug("CAPTURE: robust pipeline start")

    # 1. Syscall
    dll_path = _find_thirdeye_dll()
    if dll_path:
        data = _try_capture("syscall", lambda: _capture_syscall(dll_path))
        if data:
            return (data, "image/png")

    # 2. GDI CreateDC("DISPLAY") — bypasses some hooks on GetDC(0)
    data = _try_capture("gdi_display", _capture_gdi_display_dc)
    if data:
        return (data, "image/png")

    # 3. GDI + CAPTUREBLT
    data = _try_capture("gdi_captureblt", _capture_gdi_captureblt)
    if data:
        return (data, "image/png")

    # 4. GDI virtual screen
    data = _try_capture("gdi_virtual", _capture_gdi_virtual)
    if data:
        return (data, "image/png")

    # 5. GDI standard (accept even if blank — last resort)
    data = _try_capture("gdi", _capture_gdi, validate=False)
    if data:
        return (data, "image/png")

    # 6. DxgiCapture.dll
    dxgi_dll = _find_dxgi_dll()
    if dxgi_dll:
        data = _try_capture("dxgi_dll", _capture_dxgi_subprocess)
        if data:
            return (data, "image/png")

    raise RuntimeError("ALL capture methods failed")


def stealth_capture() -> Tuple[bytes, str]:
    """Stealth-first screen capture.

    Pipeline:
      1. Syscall via thirdeye.dll (best stealth)
      2. Check WDA — if none, use robust_capture
      3. If WDA detected — try methods that bypass WDA, else abort
    """
    # Step 1: Syscall (best)
    dll_path = _find_thirdeye_dll()
    if dll_path:
        data = _try_capture("syscall", lambda: _capture_syscall(dll_path))
        if data:
            return (data, "image/png")

    # Step 2: Check WDA
    protected = find_protected_windows()

    if not protected:
        return robust_capture()

    # Step 3: WDA detected — try DxgiCapture.dll
    dxgi_dll = _find_dxgi_dll()
    if dxgi_dll:
        data = _try_capture("dxgi_dll", _capture_dxgi_subprocess)
        if data:
            return (data, "image/png")

    raise StealthAbort(protected)


def force_capture() -> Tuple[bytes, str]:
    """Force capture — tries everything."""
    return robust_capture()


def capture_desktop_stealth(force: bool = False) -> Tuple[bytes, str]:
    """Unified entry point for CodePilot."""
    if force:
        return force_capture()
    return stealth_capture()
