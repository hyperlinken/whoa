"""DWMShield v3 — Stealth-First Screen Capture (Pure Python, standalone).

Stealth priority: capture ONLY if undetectable. Abort if compromised.

Pipeline:
  1. Try syscall capture via thirdeye.dll  (zero footprint, ignores WDA)
  2. Check for WDA-protected windows
     - None found  → GDI BitBlt is safe → capture
     - Found       → ABORT (stripping WDA = detectable)

All win32 calls use ctypes — no Rust/C build required at runtime.
Just place thirdeye.dll next to this file (or in the same dir as the .exe)
for stealth capture of WDA-protected windows.
"""

import ctypes
import ctypes.wintypes
import io
import os
import sys
import struct
from enum import IntEnum
from typing import Optional, Tuple

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
DIB_RGB_COLORS = 0
BI_RGB = 0

# Callback type for EnumWindows
WNDENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.BOOL,
    ctypes.wintypes.HWND,
    ctypes.wintypes.LPARAM,
)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.wintypes.LONG),
        ("biHeight", ctypes.wintypes.LONG),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.wintypes.LONG),
        ("biYPelsPerMeter", ctypes.wintypes.LONG),
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
# THIRDEYE.DLL SYSCALL CAPTURE  (stealth — zero footprint)
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
        # Next to this script
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "thirdeye.dll"),
        # Next to the main exe/script
        os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "thirdeye.dll"),
        # Current working directory
        os.path.join(os.getcwd(), "thirdeye.dll"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _capture_syscall(dll_path: str) -> bytes:
    """Capture screen via thirdeye.dll syscalls. Returns PNG bytes."""
    lib = ctypes.WinDLL(dll_path)

    # Set up function signatures
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

    # Create context
    ctx = ctypes.c_void_p()
    rc = lib.Thirdeye_CreateContext(ctypes.byref(ctx))
    if rc != 0 or not ctx:
        raise RuntimeError(f"Thirdeye_CreateContext failed (rc={rc})")

    try:
        # Capture to buffer as PNG, bypass WDA
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
# GDI BITBLT CAPTURE  (safe only when no WDA-protected windows exist)
# ═══════════════════════════════════════════════════════════════════════════

def _capture_gdi() -> bytes:
    """Capture primary screen via GDI BitBlt. Returns PNG bytes."""
    width = _user32.GetSystemMetrics(SM_CXSCREEN)
    height = _user32.GetSystemMetrics(SM_CYSCREEN)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid screen dimensions: {width}x{height}")

    # Get desktop DC
    desktop_dc = _user32.GetDC(0)
    if not desktop_dc:
        raise RuntimeError("GetDC(desktop) failed")

    # Create memory DC + compatible bitmap
    mem_dc = _gdi32.CreateCompatibleDC(desktop_dc)
    bitmap = _gdi32.CreateCompatibleBitmap(desktop_dc, width, height)
    old_obj = _gdi32.SelectObject(mem_dc, bitmap)

    try:
        # BitBlt the screen
        _gdi32.BitBlt(mem_dc, 0, 0, width, height, desktop_dc, 0, 0, SRCCOPY)

        # Extract pixels via GetDIBits
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB

        pixel_data = ctypes.create_string_buffer(width * height * 4)
        lines = _gdi32.GetDIBits(
            mem_dc, bitmap, 0, height, pixel_data, ctypes.byref(bmi), DIB_RGB_COLORS
        )
        if lines == 0:
            raise RuntimeError("GetDIBits returned 0 scanlines")

        # Convert BGRA → RGBA
        raw = bytearray(pixel_data.raw)
        for i in range(0, len(raw), 4):
            raw[i], raw[i + 2] = raw[i + 2], raw[i]  # swap B↔R

        # Encode as PNG using PIL (already a dependency in vinod/)
        from PIL import Image
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
# DXGI CAPTURE via DxgiCapture.dll  (bypasses WDA_MONITOR on many systems)
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


def _capture_dxgi() -> bytes:
    """Capture screen via DXGI Desktop Duplication (C# DLL). Returns PNG bytes.

    Uses CreateDC("DISPLAY") with CAPTUREBLT flag which captures from the
    display driver directly, bypassing WDA_MONITOR on many Windows versions.
    """
    import clr as _clr
    dll_path = _find_dxgi_dll()
    if not dll_path:
        raise RuntimeError("DxgiCapture.dll not found")

    _clr.AddReference(dll_path)
    from DxgiCapture import ScreenCapture
    result = ScreenCapture.CaptureBestEffort()
    return bytes(result)


def _capture_dxgi_subprocess() -> bytes:
    """Fallback: call DxgiCapture via a subprocess with .NET runtime."""
    import subprocess
    import base64

    dll_path = _find_dxgi_dll()
    if not dll_path:
        raise RuntimeError("DxgiCapture.dll not found")

    # Create a tiny C# script that loads the DLL and outputs base64 PNG
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

    # Compile if needed
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


def stealth_capture() -> Tuple[bytes, str]:
    """Stealth-first screen capture. Returns (png_bytes, mime_type).

    Pipeline:
      1. Try syscall capture via thirdeye.dll (zero footprint)
      2. Check for WDA-protected windows
         - None found -> GDI BitBlt is safe -> capture
         - Found -> try DXGI capture (bypasses WDA on many systems)
         - DXGI fails -> raise StealthAbort

    Returns:
        Tuple of (image_bytes, mime_type)

    Raises:
        StealthAbort: If stealth capture is not possible
        RuntimeError: If capture fails for technical reasons
    """
    # -- Step 1: Syscall capture (best stealth) --
    dll_path = _find_thirdeye_dll()
    if dll_path:
        try:
            png_bytes = _capture_syscall(dll_path)
            return (png_bytes, "image/png")
        except Exception as e:
            print(f"  [stealth] Syscall capture failed: {e}")

    # -- Step 2: Check WDA --
    protected = find_protected_windows()

    if not protected:
        # No WDA windows -> GDI is safe
        png_bytes = _capture_gdi()
        return (png_bytes, "image/png")

    # -- Step 3: WDA detected -> try DXGI bypass --
    dxgi_dll = _find_dxgi_dll()
    if dxgi_dll:
        try:
            png_bytes = _capture_dxgi_subprocess()
            return (png_bytes, "image/png")
        except Exception as e:
            print(f"  [stealth] DXGI capture failed: {e}")

    # -- Step 4: All stealth methods exhausted --
    raise StealthAbort(protected)


def force_capture() -> Tuple[bytes, str]:
    """Force capture using the best available method. NOT stealth.

    Tries syscall first, then DXGI, then GDI.
    """
    # Try syscall first
    dll_path = _find_thirdeye_dll()
    if dll_path:
        try:
            png_bytes = _capture_syscall(dll_path)
            return (png_bytes, "image/png")
        except Exception:
            pass

    # Try DXGI
    dxgi_dll = _find_dxgi_dll()
    if dxgi_dll:
        try:
            png_bytes = _capture_dxgi_subprocess()
            return (png_bytes, "image/png")
        except Exception:
            pass

    # Fall back to GDI
    png_bytes = _capture_gdi()
    return (png_bytes, "image/png")


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
