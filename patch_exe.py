"""Patch PE version-info so Task Manager Processes tab shows custom name."""
import ctypes, ctypes.wintypes, struct, sys
from pathlib import Path

_k32 = ctypes.windll.kernel32

def _pad(d):
    r = len(d) % 4
    return d + b"\x00" * ((4 - r) if r else 0)

def _se(k, v):
    kb = k.encode("utf-16-le") + b"\x00\x00"
    vb = v.encode("utf-16-le") + b"\x00\x00"
    h = _pad(struct.pack("<HHH", 0, len(v)+1, 1) + kb)
    b = bytearray(h + vb)
    struct.pack_into("<H", b, 0, len(b))
    return _pad(bytes(b))

def _st(lcp, s):
    k = lcp.encode("utf-16-le") + b"\x00\x00"
    h = _pad(struct.pack("<HHH", 0, 0, 1) + k)
    c = b"".join(_se(a, b) for a, b in s.items())
    d = bytearray(h + c); struct.pack_into("<H", d, 0, len(d))
    return _pad(bytes(d))

def _sfi(lcp, s):
    k = "StringFileInfo".encode("utf-16-le") + b"\x00\x00"
    h = _pad(struct.pack("<HHH", 0, 0, 1) + k)
    d = bytearray(h + _st(lcp, s)); struct.pack_into("<H", d, 0, len(d))
    return _pad(bytes(d))

def _vfi(l, c):
    k1 = "Translation".encode("utf-16-le") + b"\x00\x00"
    v = struct.pack("<HH", l, c)
    h1 = _pad(struct.pack("<HHH", 0, len(v), 0) + k1)
    d1 = bytearray(h1 + v); struct.pack_into("<H", d1, 0, len(d1))
    k2 = "VarFileInfo".encode("utf-16-le") + b"\x00\x00"
    h2 = _pad(struct.pack("<HHH", 0, 0, 1) + k2)
    d2 = bytearray(h2 + _pad(bytes(d1))); struct.pack_into("<H", d2, 0, len(d2))
    return _pad(bytes(d2))

def build(n):
    f = struct.pack("<IIIIIIIIIIIII", 0xFEEF04BD, 0x00010000, 0x00010000, 0,
        0x00010000, 0, 0x3F, 0, 0x00040004, 1, 0, 0, 0)
    s = {"CompanyName":n,"FileDescription":n,"FileVersion":"1.0",
         "InternalName":n,"OriginalFilename":f"{n}.exe","ProductName":n,"ProductVersion":"1.0"}
    sfi = _sfi("040904B0", s); vfi = _vfi(0x0409, 0x04B0)
    k = "VS_VERSION_INFO".encode("utf-16-le") + b"\x00\x00"
    h = _pad(struct.pack("<HHH", 0, len(f), 0) + k)
    d = bytearray(h + _pad(f) + sfi + vfi); struct.pack_into("<H", d, 0, len(d))
    return bytes(d)

def patch(exe, name):
    data = build(name)
    _k32.BeginUpdateResourceW.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.wintypes.BOOL]
    _k32.BeginUpdateResourceW.restype = ctypes.wintypes.HANDLE
    _k32.UpdateResourceW.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.LPCWSTR, ctypes.wintypes.WORD, ctypes.c_void_p, ctypes.wintypes.DWORD]
    _k32.UpdateResourceW.restype = ctypes.wintypes.BOOL
    _k32.EndUpdateResourceW.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.BOOL]
    _k32.EndUpdateResourceW.restype = ctypes.wintypes.BOOL
    h = _k32.BeginUpdateResourceW(exe, False)
    if not h: return False
    ok = _k32.UpdateResourceW(h, ctypes.cast(16, ctypes.wintypes.LPCWSTR),
        ctypes.cast(1, ctypes.wintypes.LPCWSTR), 0x0409, data, len(data))
    if not ok: _k32.EndUpdateResourceW(h, True); return False
    return bool(_k32.EndUpdateResourceW(h, False))

if __name__ == "__main__":
    exe = Path(sys.argv[1]).resolve()
    name = sys.argv[2] if len(sys.argv) > 2 else exe.stem
    patch(str(exe), name)
