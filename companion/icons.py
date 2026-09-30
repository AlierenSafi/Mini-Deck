"""32x32 RGB565 icons; Windows shell extraction runs outside the Tk thread."""

import ctypes
from ctypes import wintypes as W
import hashlib
import os
from pathlib import Path
import shutil
import struct
import threading
import unicodedata
import configparser
import re
from functools import lru_cache
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent
SIZE = 32
BACKGROUND = (38, 46, 51)  # Graphite & Mint firmware panel, RGB565 0x2166.


def deck_label(item):
    defaults = {
        "Onceki parca": "ONCEKI",
        "Oynat / duraklat": "OYNAT",
        "Sonraki parca": "SONRAKI",
        "Sesi azalt": "SES -",
        "Sesi ac / kapat": "SESSIZ",
        "Sesi artir": "SES +",
        "Dosya Gezgini": "DOSYALAR",
        "Hesap Makinesi": "HESAP",
        "Not Defteri": "NOTLAR",
        "Masaustunu goster": "MASAUSTU",
        "Gorev Yoneticisi": "GOREVLER",
        "Windows Ayarlari": "AYARLAR",
    }
    text = item.get("label") or defaults.get(item["name"], item["name"])
    text = text.translate(str.maketrans("ıİşŞğĞçÇöÖüÜ", "iIsSgGcCoOuU"))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()
    return "".join(c for c in text if c.isalnum() or c in " -./")[:10] or "SLOT"


def rgb565(image):
    image = image.convert("RGB").resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    return b"".join(
        struct.pack(">H", ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))
        for r, g, b in image.get_flattened_data()
    )


def themed_pixels(image, monochrome=False):
    """v6: transparent pixels use reserved RGB565 0x0001; opaque black stays black."""
    image = image.convert("RGBA").resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    result = []
    for r, g, b, a in image.get_flattened_data():
        v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        result.append(1 if a < 128 else 2 if monochrome else (0 if v in (1, 2) else v))
    return b"".join(struct.pack(">H", v) for v in result)


def fallback_icon(item):
    image = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    color = "#80c9b0"
    if item["type"] == "empty":
        d.line((7, 12, 17, 12), fill="#8292aa", width=2)
        d.line((12, 7, 12, 17), fill="#8292aa", width=2)
    elif item["type"] == "keys" and len(item.get("keys", [])) == 1:
        key = item["keys"][0]
        if key in ("PREVIOUS", "PLAY", "NEXT"):
            d.polygon([(6, 4), (6, 20), (19, 12)], fill=color)
            if key == "NEXT":
                d.rectangle((20, 4, 22, 20), fill=color)
            elif key == "PREVIOUS":
                image = ImageOps.mirror(image)
                ImageDraw.Draw(image).rectangle((1, 4, 3, 20), fill=color)
        else:
            d.rectangle((2, 9, 6, 15), fill=color)
            d.polygon([(6, 9), (11, 4), (11, 20), (6, 15)], fill=color)
            d.line((15, 12, 22, 12), fill=color, width=2)
            if key == "VOLUME_UP":
                d.line((19, 8, 19, 16), fill=color, width=2)
            if key == "MUTE":
                d.line((15, 8, 22, 16), fill=color, width=2)
    elif item["type"] == "settings":
        for y, x in ((5, 8), (12, 17), (19, 10)):
            d.line((2, y, 22, y), fill=color, width=2)
            d.rectangle((x - 1, y - 3, x + 1, y + 3), fill=color)
    elif item["type"] == "keys":
        d.rounded_rectangle((1, 4, 22, 20), radius=3, outline=color, width=2)
        for y in (8, 12):
            for x in (5, 10, 15):
                d.rectangle((x, y, x + 2, y + 1), fill=color)
        d.line((7, 16, 17, 16), fill=color, width=2)
    else:
        d.rounded_rectangle((3, 2, 21, 22), radius=4, fill="#647fff")
        d.rectangle((7, 7, 17, 16), outline="white", width=2)
    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def shell_icon(path, index=None):
    class SHFILEINFO(ctypes.Structure):
        _fields_ = [
            ("hIcon", W.HANDLE),
            ("iIcon", ctypes.c_int),
            ("dwAttributes", W.DWORD),
            ("szDisplayName", W.WCHAR * 260),
            ("szTypeName", W.WCHAR * 80),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", W.DWORD),
            ("biWidth", W.LONG),
            ("biHeight", W.LONG),
            ("biPlanes", W.WORD),
            ("biBitCount", W.WORD),
            ("biCompression", W.DWORD),
            ("biSizeImage", W.DWORD),
            ("biXPelsPerMeter", W.LONG),
            ("biYPelsPerMeter", W.LONG),
            ("biClrUsed", W.DWORD),
            ("biClrImportant", W.DWORD),
        ]

    shell = ctypes.WinDLL("shell32")
    user = ctypes.WinDLL("user32")
    gdi = ctypes.WinDLL("gdi32")
    shell.SHGetFileInfoW.argtypes = [W.LPCWSTR, W.DWORD, ctypes.POINTER(SHFILEINFO), W.UINT, W.UINT]
    shell.SHGetFileInfoW.restype = ctypes.c_size_t
    user.DestroyIcon.argtypes = [W.HANDLE]
    user.DestroyIcon.restype = W.BOOL
    gdi.CreateCompatibleDC.argtypes = [W.HDC]
    gdi.CreateCompatibleDC.restype = W.HDC
    gdi.CreateDIBSection.argtypes = [
        W.HDC,
        ctypes.POINTER(BITMAPINFOHEADER),
        W.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        W.HANDLE,
        W.DWORD,
    ]
    gdi.CreateDIBSection.restype = W.HBITMAP
    gdi.SelectObject.argtypes = [W.HDC, W.HANDLE]
    gdi.SelectObject.restype = W.HANDLE
    gdi.DeleteObject.argtypes = [W.HANDLE]
    gdi.DeleteDC.argtypes = [W.HDC]
    user.DrawIconEx.argtypes = [
        W.HDC,
        ctypes.c_int,
        ctypes.c_int,
        W.HANDLE,
        ctypes.c_int,
        ctypes.c_int,
        W.UINT,
        W.HBRUSH,
        W.UINT,
    ]
    user.DrawIconEx.restype = W.BOOL
    info = SHFILEINFO()
    if index is None:
        if not shell.SHGetFileInfoW(str(path), 0, ctypes.byref(info), ctypes.sizeof(info), 0x100):
            raise OSError(f"Simge alınamadı: {path}")
    else:
        shell.ExtractIconExW.argtypes = [
            W.LPCWSTR,
            ctypes.c_int,
            ctypes.POINTER(W.HANDLE),
            ctypes.POINTER(W.HANDLE),
            W.UINT,
        ]
        shell.ExtractIconExW.restype = W.UINT
        handle = W.HANDLE()
        if not shell.ExtractIconExW(str(path), index, ctypes.byref(handle), None, 1):
            raise OSError("Simge kaynağı okunamadı.")
        info.hIcon = handle.value
    dc = bitmap = previous = None
    try:
        dc = gdi.CreateCompatibleDC(None)
        header = BITMAPINFOHEADER(
            biSize=ctypes.sizeof(BITMAPINFOHEADER),
            biWidth=SIZE,
            biHeight=-SIZE,
            biPlanes=1,
            biBitCount=32,
        )
        bits = ctypes.c_void_p()
        bitmap = gdi.CreateDIBSection(dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
        if not dc or not bitmap or not bits.value:
            raise OSError("Simge bitmap alanı oluşturulamadı.")
        previous = gdi.SelectObject(dc, bitmap)
        samples = []
        for base in (0, 255):
            fill = bytes((base, base, base, 255)) * (SIZE * SIZE)
            ctypes.memmove(bits.value, fill, len(fill))
            if not user.DrawIconEx(dc, 0, 0, info.hIcon, SIZE, SIZE, 0, None, 3):
                raise OSError("Simge çizilemedi.")
            gdi.GdiFlush()
            samples.append(
                Image.frombytes(
                    "RGB", (SIZE, SIZE), ctypes.string_at(bits, SIZE * SIZE * 4), "raw", "BGRX"
                )
            )
        pixels = []
        for dark, light in zip(samples[0].get_flattened_data(), samples[1].get_flattened_data()):
            alpha = max(0, min(255, 255 - round(sum(w - b for b, w in zip(dark, light)) / 3)))
            pixels.append(
                tuple(min(255, round(c * 255 / alpha)) for c in dark) + (alpha,)
                if alpha
                else (0, 0, 0, 0)
            )
        image = Image.new("RGBA", (SIZE, SIZE))
        image.putdata(pixels)
        return image
    finally:
        if previous and dc:
            gdi.SelectObject(dc, previous)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if dc:
            gdi.DeleteDC(dc)
        if info.hIcon:
            user.DestroyIcon(info.hIcon)


def shortcut_icon_file(path):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1254"):
        try:
            parser.read_string(raw.decode(encoding))
            break
        except (UnicodeError, configparser.Error):
            continue
    value = parser.get("InternetShortcut", "IconFile", fallback="").strip().strip('"')
    if value:
        candidate = Path(os.path.expandvars(value))
        if not candidate.is_absolute():
            candidate = Path(path).parent / candidate
        if candidate.is_file():
            return candidate
    return None


def image_icon(path):
    with Image.open(path) as source:
        source = source.convert("RGBA")
        source.thumbnail((SIZE, SIZE), Image.Resampling.LANCZOS)
        image = Image.new("RGBA", (SIZE, SIZE))
        image.alpha_composite(source, ((SIZE - source.width) // 2, (SIZE - source.height) // 2))
        return image


@lru_cache(maxsize=256)
def cached_file_icon(path, modified, size):
    p = Path(path)
    if p.suffix.lower() == ".lnk":
        try:
            import comtypes
            import comtypes.client

            comtypes.CoInitialize()
            try:
                shortcut = comtypes.client.CreateObject(
                    "WScript.Shell", dynamic=True
                ).CreateShortcut(str(p))
                location = shortcut.IconLocation
                if location:
                    file, separator, number = location.rpartition(",")
                    icon_path = Path(
                        os.path.expandvars((file if separator else location).strip().strip('"'))
                    )
                    if icon_path.is_file():
                        try:
                            return image_icon(icon_path)
                        except OSError:
                            try:
                                return shell_icon(icon_path, int(number) if separator else 0)
                            except (OSError, ValueError):
                                pass
                target = shortcut.TargetPath
                if target and Path(target).is_file() and Path(target).suffix.lower() == ".url":
                    stat = Path(target).stat()
                    return cached_file_icon(target, stat.st_mtime_ns, stat.st_size)
                if target and Path(target).is_file():
                    return shell_icon(target)
            finally:
                comtypes.CoUninitialize()
        except (OSError, ImportError, AttributeError):
            pass
    if p.suffix.lower() == ".url":
        icon = shortcut_icon_file(p)
        if icon:
            try:
                return image_icon(icon)
            except OSError:
                return shell_icon(icon)
    return shell_icon(p)


def get_icon(item):
    if item.get("icon"):
        path = Path(item["icon"])
        if not path.is_absolute():
            path = ROOT / path
        return image_icon(path)
    path = None
    if item["type"] == "launch":
        path = shutil.which(item["argv"][0]) or item["argv"][0]
    elif item["type"] == "open":
        path = item["path"]
    if path and str(path).startswith("steam://"):
        appid = re.search(r"(\d+)$", str(path))
        if appid:
            for name, link in installed_shortcuts(include_steam=False):
                if link.lower().endswith(".url"):
                    try:
                        raw = Path(link).read_text(encoding="utf-8-sig", errors="replace")
                        if re.search(
                            r"URL=steam://(?:rungameid|run)/" + appid[1] + r"(?:\s|/|$)", raw
                        ):
                            icon = shortcut_icon_file(link)
                            if icon:
                                return image_icon(icon)
                    except OSError:
                        pass
            for root in steam_roots():
                cache = root / "appcache/librarycache"
                for pattern in (appid[1] + "_icon.*", appid[1] + "/icon.*"):
                    for candidate in cache.glob(pattern):
                        try:
                            return image_icon(candidate)
                        except OSError:
                            pass
    if path and os.name == "nt" and Path(path).exists():
        stat = Path(path).stat()
        return cached_file_icon(str(path), stat.st_mtime_ns, stat.st_size).copy()
    return fallback_icon(item)


def import_icon(path):
    with Image.open(path) as source:
        source = source.convert("RGBA")
        source.thumbnail((128, 128), Image.Resampling.LANCZOS)
        digest = hashlib.sha256(source.tobytes() + str(source.size).encode()).hexdigest()[:24]
        target = ROOT / "assets" / f"{digest}.png"
        target.parent.mkdir(exist_ok=True)
        source.save(target)
    return str(target.relative_to(ROOT))


# Icon extraction can be slow; produce immutable layout snapshots outside the UI thread.
class AssetWorker(threading.Thread):
    def __init__(self, actions, emit, stop):
        super().__init__(daemon=True, name="deck-icons")
        self.actions, self.emit, self.stop = actions, emit, stop
        self.wake = threading.Event()
        self.wake.set()

    def run(self):
        last = None
        while not self.stop.is_set():
            self.wake.wait(0.5)
            self.wake.clear()
            revision, items = self.actions.snapshot()
            if revision == last:
                continue
            icons = []
            for item in items:
                if self.stop.is_set():
                    return
                try:
                    icons.append(get_icon(item))
                except (OSError, ValueError) as exc:
                    icons.append(fallback_icon(item))
                    self.emit("log", f"Simge yerine varsayılan kullanıldı: {exc}")
            if self.actions.revision != revision:
                continue
            self.emit(
                "layout",
                {
                    "revision": revision,
                    "items": items,
                    "images": icons,
                    "pixels": [
                        rgb565(
                            Image.alpha_composite(
                                Image.new("RGBA", (SIZE, SIZE), BACKGROUND + (255,)),
                                im.convert("RGBA"),
                            )
                        )
                        .hex()
                        .upper()
                        for im in icons
                    ],
                    "themed_pixels": [
                        themed_pixels(
                            im, not item.get("icon") and item["type"] in ("keys", "settings")
                        )
                        .hex()
                        .upper()
                        for im, item in zip(icons, items)
                    ],
                },
            )
            last = revision


def steam_roots():
    if os.name != "nt":
        return []
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            root = Path(winreg.QueryValueEx(key, "SteamPath")[0])
        return [root]
    except OSError:
        return []


def installed_shortcuts(include_steam=True):
    """Start Menu entries, including per-user app shortcuts; no registry changes."""
    roots = [
        Path(os.environ.get("ProgramData", "C:/ProgramData"))
        / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path.home() / "Desktop",
        Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "Desktop",
        Path.home() / "OneDrive/Desktop",
    ]
    result = {}
    for root in roots:
        if root.is_dir():
            for path in (p for p in root.rglob("*") if p.suffix.lower() in (".lnk", ".url")):
                result[str(path)] = (path.stem, str(path))
                if len(result) >= 2000:
                    break
    if include_steam:
        for root in steam_roots():
            libraries = {root}
            try:
                text = (root / "steamapps/libraryfolders.vdf").read_text(encoding="utf-8")
                libraries.update(
                    Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', text)
                )
            except OSError:
                pass
            for library in libraries:
                for manifest in (library / "steamapps").glob("appmanifest_*.acf"):
                    try:
                        text = manifest.read_text(encoding="utf-8")
                        name = re.search(r'"name"\s+"([^"]+)"', text)
                        appid = re.search(r'"appid"\s+"(\d+)"', text)
                        if name and appid:
                            result["steam:" + appid[1]] = (name[1], "steam://rungameid/" + appid[1])
                    except OSError:
                        pass
    # Prefer direct Steam entries, then web shortcuts; avoid repeated Desktop/Start Menu copies.
    unique = {}
    for name, path in sorted(
        result.values(),
        key=lambda v: (
            0 if v[1].startswith("steam://") else 1 if v[1].lower().endswith(".url") else 2,
            v[1],
        ),
    ):
        key = re.sub(r"[^\w]", "", name.casefold())
        unique.setdefault(key, (name, path))
    return sorted(unique.values(), key=lambda value: value[0].casefold())
