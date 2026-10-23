# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Menu entries (.desktop) that start an app through appjail, optionally for chosen MIME types.

The AppImage's own .desktop file is untrusted: its Exec, Actions, TryExec and MimeType would act outside the jail. Only a
few display fields are read from it (and sanitised); the entry itself is generated here and written by the host-side CLI.
Only files carrying the X-Appjail-App marker are ever touched.
"""

import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from . import appimage, jail, store
from .textsafe import clean

MARKER = "X-Appjail-App"
MAX_DESKTOP_BYTES = 64 * 1024
MAX_PNG_BYTES = 1024 * 1024
MAX_SVG_BYTES = 2 * 1024 * 1024
ICON_SIZE_RANGE = (16, 1024)
SVG_SIZE = 256
RSVG = "/usr/bin/rsvg-convert"
MAX_MIMES = 32
MAX_FIELD = 200

DISPLAY_KEYS = ("Name", "Comment", "GenericName", "Categories", "Keywords", "Icon", "MimeType")
_CATEGORIES = re.compile(r"[A-Za-z0-9._-]+(;[A-Za-z0-9._-]+)*;?")
_ICON_NAME = re.compile(r"[A-Za-z0-9._+-]{1,100}")
_MIME = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}")
# Types that must never be advertised: URL handlers, things that run code, launchers of other programs.
_MIME_DENY_PREFIX = ("x-scheme-handler/", "inode/")
_MIME_DENY = frozenset({
    "application/x-desktop", "application/x-executable", "application/x-sharedlib", "application/x-pie-executable",
    "application/x-shellscript", "application/x-appimage", "application/vnd.appimage", "application/x-ms-dos-executable",
    "application/x-msdos-program", "application/x-java-archive", "application/x-java", "application/x-perl",
    "application/x-php", "application/x-python", "application/x-python-code", "application/x-ruby",
    "application/x-awk", "application/x-csh", "application/x-sh", "application/x-bat", "application/x-msi",
    "application/vnd.debian.binary-package", "application/x-rpm", "application/x-ms-shortcut", "application/x-executable-script",
    "text/x-python", "text/x-python3", "text/x-perl", "text/x-shellscript", "text/x-sh", "text/x-csh", "text/x-ruby",
    "text/x-php", "text/x-java", "text/x-lua", "text/x-awk", "text/x-bat", "text/x-msdos-batch",
})


class DesktopError(Exception):
    """Something the user has to be told; the message is shown as is."""


# -- locations ----------------------------------------------------------------------

def data_home():
    base = os.environ.get("XDG_DATA_HOME")
    return Path(base) if base else Path.home() / ".local/share"


def applications_dir():
    return data_home() / "applications"


def entry_path(name):
    return applications_dir() / f"appjail-{name}.desktop"


def icon_files(name):
    return sorted((data_home() / "icons/hicolor").glob(f"*/apps/appjail-{name}.png"))


# -- reading the app's own .desktop file ---------------------------------------------

def parse_desktop(text):
    """The unlocalised DISPLAY_KEYS of the [Desktop Entry] group (the last assignment wins)."""
    found, inside = {}, False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            inside = line == "[Desktop Entry]"
        elif inside and "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            if key.strip() in DISPLAY_KEYS:
                found[key.strip()] = value.strip()
    return found


def read_app_desktop(root):
    """Fields of the first top-level *.desktop file of the extracted tree (symlinks are not followed), or {}."""
    root = Path(root)
    for path in sorted(root.glob("*.desktop")):
        try:
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_DESKTOP_BYTES:
                continue
            return parse_desktop(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return {}


def _text(value, limit=MAX_FIELD):
    return clean(value or "", limit).replace("\\", "").strip()


def display_fields(fields, name):
    """The sanitised subset of the app's fields that goes into the entry."""
    out = {"Name": _text(fields.get("Name"), 80) or name}
    if comment := _text(fields.get("Comment")):
        out["Comment"] = comment
    if generic := _text(fields.get("GenericName"), 80):
        out["GenericName"] = generic
    categories = (fields.get("Categories") or "").strip()
    if categories and len(categories) <= MAX_FIELD and _CATEGORIES.fullmatch(categories):
        out["Categories"] = categories if categories.endswith(";") else categories + ";"
    if keywords := _text(fields.get("Keywords")):
        out["Keywords"] = keywords if keywords.endswith(";") else keywords + ";"
    return out


# -- MIME types -----------------------------------------------------------------------

def split_mimes(raw):
    """(kept, ignored) from a MimeType value: well-formed, not on the deny list, no duplicates, at most MAX_MIMES."""
    kept, ignored = [], []
    for item in (raw or "").split(";"):
        item = item.strip()
        if not item or item in kept or item in ignored:
            continue
        low = item.lower()
        if (not _MIME.fullmatch(item) or low != item or item in _MIME_DENY or item.startswith(_MIME_DENY_PREFIX)
                or len(kept) >= MAX_MIMES):
            ignored.append(clean(item, 60))
        else:
            kept.append(item)
    return kept, ignored


# -- the entry -----------------------------------------------------------------------

def launcher_argv():
    """How the entry starts appjail: the installed command, or the interpreter running this package."""
    found = shutil.which("appjail")
    return [os.path.realpath(found)] if found else [os.path.realpath(sys.executable), "-m", "appjail"]


def _quote_arg(arg):
    """One Exec argument as the Desktop Entry spec wants it (before the string-level escaping of the file format)."""
    arg = arg.replace("%", "%%")
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", arg):
        return arg
    return '"' + re.sub(r'(["`$\\])', r"\\\1", arg) + '"'


def exec_line(name, mimes, rw=False, argv=None):
    """Exec= value. With types, files come as %F after `--` (so a file named -x is not an option); without, a plain run."""
    argv = argv or launcher_argv()
    if mimes:
        words = [*argv, "open", name, *(["--rw"] if rw else []), "--", "%F"]
        return " ".join(_quote_arg(w) if w != "%F" else w for w in words)
    return " ".join(_quote_arg(w) for w in [*argv, "run", name])


def _escape(value):
    return value.replace("\\", "\\\\")


def build_entry(name, fields, mimes=(), rw=False, argv=None, icon=False):
    lines = ["[Desktop Entry]", "Type=Application", f"{MARKER}={name}"]
    shown = display_fields(fields, name)
    lines.append(f"Name={_escape(shown['Name'])} (appjail)")
    for key in ("Comment", "GenericName", "Categories", "Keywords"):
        if key in shown:
            lines.append(f"{key}={_escape(shown[key])}")
    lines.append("Exec=" + _escape(exec_line(name, mimes, rw, argv)))
    lines.append("Terminal=false")
    if icon:
        lines.append(f"Icon=appjail-{name}")
    if mimes:
        lines.append("MimeType=" + ";".join(mimes) + ";")
    return "\n".join(lines) + "\n"


def marker_of(path):
    """The app name in the X-Appjail-App marker of an entry file, or None if it is not ours."""
    try:
        if os.lstat(path).st_size > MAX_DESKTOP_BYTES or not Path(path).is_file():
            return None
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(MARKER + "="):
                return line.partition("=")[2].strip()
    except OSError:
        pass
    return None


def installed_state(name):
    """(mimes, rw) of the installed entry of an app, or None when there is none (or the file is not ours)."""
    path = entry_path(name)
    if marker_of(path) != name:
        return None
    mimes, rw = [], False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("MimeType="):
            mimes = [m for m in line.partition("=")[2].split(";") if m]
        elif line.startswith("Exec=") and " --rw " in line:
            rw = True
    return mimes, rw


def write_entry(name, text):
    """Write the entry atomically; never replace a file that is not ours."""
    path = entry_path(name)
    if os.path.lexists(path) and marker_of(path) != name:
        raise DesktopError(f"{path} exists and was not created by appjail; not touching it")
    path.parent.mkdir(parents=True, exist_ok=True)
    store.atomic_write(path, text)
    return path


# -- icons ---------------------------------------------------------------------------

def png_size(data):
    """(width, height) of a PNG after checking the signature and the first (IHDR) chunk, else None."""
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    lo, hi = ICON_SIZE_RANGE
    return (width, height) if width == height and lo <= width <= hi else None


def find_icon(root, fields):
    """Bytes of the app's icon (PNG or SVG) read from the tree without leaving it, or None."""
    names = []
    icon = fields.get("Icon", "")
    if _ICON_NAME.fullmatch(icon):
        names += [f"{icon}.png", f"{icon}.svg", icon]
        names += [f"usr/share/icons/hicolor/{s}/apps/{icon}.png" for s in ("256x256", "512x512", "128x128", "64x64", "48x48")]
        names += [f"usr/share/icons/hicolor/scalable/apps/{icon}.svg"]
    names.append(".DirIcon")
    for rel in names:
        try:
            path = appimage.resolve_entry(root, rel, executable=False)
            if os.stat(path).st_size > MAX_SVG_BYTES:
                continue
            return Path(path).read_bytes()
        except (appimage.UnsafeTree, OSError):
            continue
    return None


def svg_to_png(svg, convert=None):
    """PNG bytes for an SVG, rendered by rsvg-convert inside a jail with no network; the host never decodes the SVG."""
    convert = convert or RSVG
    if not os.access(convert, os.X_OK):
        raise DesktopError("rsvg-convert is not installed (apt install librsvg2-bin): no icon")
    with tempfile.TemporaryDirectory(prefix="appjail-icon-") as work:
        src, out = Path(work, "in.svg"), Path(work, "out")
        out.mkdir()
        src.write_bytes(svg)
        cmd = [convert, "-w", str(SVG_SIZE), "-h", str(SVG_SIZE), "-f", "png", "-o", "/out/icon.png", "/app.AppImage"]
        proc = jail.run(jail.extract_args(src, out, cmd, tools=()), timeout=60, watch=(out, 4 * 1024 * 1024, 10))
        png = out / "icon.png"
        if proc.returncode != 0 or not png.is_file() or png.stat().st_size > MAX_PNG_BYTES:
            raise DesktopError("could not convert the SVG icon: " + clean(proc.stderr.strip() or "no output", 200))
        return png.read_bytes()


def install_icon(name, root, fields, convert=None):
    """Install the app's icon under hicolor as a validated PNG. Returns the size string, or None (with a reason raised
    as DesktopError only when an SVG could not be converted)."""
    data = find_icon(root, fields)
    if data is None:
        return None
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        if b"<svg" not in data[:4096].lower():
            return None
        data = svg_to_png(data, convert)
    if len(data) > MAX_PNG_BYTES or (size := png_size(data)) is None:
        return None
    remove_icons(name)
    target = data_home() / f"icons/hicolor/{size[0]}x{size[1]}/apps/appjail-{name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    store.atomic_write(target, data)
    return f"{size[0]}x{size[1]}"


def remove_icons(name):
    for path in icon_files(name):
        path.unlink(missing_ok=True)


# -- install / remove ----------------------------------------------------------------

def refresh_cache():
    """Tell the desktop about changed entries (desktop-file-utils); False when the tool is missing."""
    tool = shutil.which("update-desktop-database")
    if not tool:
        return False
    subprocess.run([tool, str(applications_dir())], capture_output=True, check=False, timeout=60)
    return True


def install(name, root, mimes=(), rw=False, argv=None, convert=None):
    """Write the entry and the icon for an app. Returns (entry path, icon size or None, icon note or None)."""
    fields = read_app_desktop(root)
    note = None
    try:
        size = install_icon(name, root, fields, convert)
    except DesktopError as e:
        size, note = None, str(e)
        remove_icons(name)
    path = write_entry(name, build_entry(name, fields, mimes, rw, argv, icon=size is not None))
    refresh_cache()
    return path, size, note


def remove(name):
    """Delete the app's entry and icons (only our own files). True if there was an entry."""
    path = entry_path(name)
    ours = marker_of(path) == name
    if ours:
        path.unlink(missing_ok=True)
    remove_icons(name)
    if ours:
        refresh_cache()
    return ours


def dangling(exists=lambda n: store.manifest_path(n).exists()):
    """Marked entries whose app is gone: [(app name, path)]."""
    out = []
    for path in sorted(applications_dir().glob("appjail-*.desktop")) if applications_dir().is_dir() else []:
        app = marker_of(path)
        if app and path.name == f"appjail-{app}.desktop" and not exists(app):
            out.append((app, path))
    return out


def mimeapps_mentions(name):
    """True when the user's mimeapps.list still names the app's entry (appjail never edits that file)."""
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "mimeapps.list"
    try:
        return f"appjail-{name}.desktop" in config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
