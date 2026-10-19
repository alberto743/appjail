# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Manifest schema, strict parser and writer (TOML).

A manifest is declarative data only: where an app comes from, what was pinned and
what the jail may do. Unknown keys and malformed values are errors, never ignored.
"""

import os
import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1

NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
# GitHub owners are alphanumeric/hyphen; repos may also hold "_" and "." but are never "." or "..".
SOURCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/(?!\.{1,2}$)[A-Za-z0-9_.-]{1,100}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PUBLISHED_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
DBUS_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*)+(\.\*)?")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

# Talking to these on the session bus is equivalent to running commands on the host or taking over
# the desktop, so a filter that allows them would not be a filter. Refused, never granted.
DBUS_BLOCKED = ("org.freedesktop.DBus", "org.freedesktop.systemd1", "org.freedesktop.Flatpak",
                "org.freedesktop.impl", "org.gnome.Shell", "org.gnome.SessionManager", "org.kde.KWin",
                "org.kde.klauncher5", "org.kde.klauncher6", "org.freedesktop.portal")
DBUS_SENSITIVE = ("org.freedesktop.secrets", "org.gnome.keyring", "org.kde.kwalletd5", "org.kde.kwalletd6")
DBUS_MIN_WILDCARD_PARTS = 3
# Owning a name lets the app be the service behind it. Impersonating a desktop service (notifications, secrets,
# polkit, the file manager, ...) would let the app intercept what other apps send there, so the desktop
# namespaces cannot be owned, except the status-notifier names an app registers for its own tray icon.
DBUS_NO_OWN = ("org.freedesktop.", "org.gnome.", "org.kde.", "org.a11y.", "com.canonical.", "org.ayatana.")
DBUS_OWN_OK = ("org.freedesktop.StatusNotifierItem", "org.kde.StatusNotifierItem")

# Portal interfaces (the part after org.freedesktop.portal.). `portals = true` allows the safe set; the
# opt-in ones must be named in `portal_interfaces`; the last group is never available to an app.
PORTAL_SAFE = ("FileChooser", "Notification", "Settings", "Trash", "Print", "Inhibit", "NetworkMonitor",
               "ProxyResolver", "Secret", "Realtime", "MemoryMonitor", "PowerProfileMonitor")
PORTAL_OPT_IN = ("OpenURI", "Email", "Screenshot", "ScreenCast", "RemoteDesktop", "GlobalShortcuts", "InputCapture",
                 "Camera", "Location", "Account", "Wallpaper", "Background", "Usb")
PORTAL_NEVER = ("Flatpak", "DynamicLauncher")

TIERS = (1, 2, 3, 4, 5)
DISPLAYS = ("wayland", "xwayland")

TOP_KEYS = {
    "schema", "name", "source", "asset_pattern", "version", "sha256",
    "evidence_tier", "published_at", "owner_id", "channel", "permissions",
}
CHANNELS = ("stable", "prerelease", "pinned")
PERM_KEYS = {"network", "audio", "gpu", "display", "dbus_filter", "dbus_own", "portals", "portal_interfaces", "userns", "dirs"}


class ManifestError(ValueError):
    """The manifest is malformed or violates the schema."""


@dataclass(frozen=True)
class Permissions:
    """Everything is denied unless granted."""
    network: bool = False
    audio: bool = False
    gpu: bool = False
    display: str = "wayland"
    dbus_filter: tuple = ()  # session-bus names the app may talk to
    dbus_own: tuple = ()  # session-bus names the app may own (and talk to): MPRIS players, single-instance names
    portals: bool = False
    portal_interfaces: tuple = ()  # opt-in portal interfaces beyond the safe set (see PORTAL_OPT_IN)
    userns: bool = False  # nested user namespaces and mounts (Electron/Chromium sandboxes, nested bwrap)
    dirs: tuple = ()  # "path" (read-only) or "path:rw"; absolute or starting with "~/"


@dataclass(frozen=True)
class Manifest:
    name: str
    source: str  # GitHub "owner/repo"
    asset_pattern: str  # fnmatch pattern for the release asset name
    version: str
    sha256: str
    evidence_tier: int
    published_at: str  # UTC, YYYY-MM-DDTHH:MM:SSZ
    owner_id: int = None  # GitHub account id of the owner; pins the account, not just the name
    channel: str = "stable"  # which releases `update` follows: stable, prerelease, or pinned (never)
    permissions: Permissions = field(default_factory=Permissions)


def _text(value, what, max_len=256):
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{what} must be a non-empty string")
    if len(value) > max_len or CONTROL_RE.search(value):
        raise ManifestError(f"{what} is too long or contains control characters")
    return value


def _match(value, regex, what):
    _text(value, what)
    if not regex.fullmatch(value):
        raise ManifestError(f"{what} has an invalid format: {value!r}")
    return value


def _bool(value, what):
    if not isinstance(value, bool):
        raise ManifestError(f"{what} must be true or false")
    return value


def _str_list(value, what):
    if not isinstance(value, list):
        raise ManifestError(f"{what} must be a list of strings")
    return [_text(v, f"{what} entry") for v in value]


def check_portal_interface(name):
    """An opt-in portal interface name; the never-allowed ones and unknown names are refused."""
    if name in PORTAL_NEVER:
        raise ManifestError(f"portal_interfaces entry {name!r} is refused: it would let the app run commands or "
                            "install launchers on the host")
    if name not in PORTAL_OPT_IN:
        raise ManifestError(f"portal_interfaces entry {name!r} is not an opt-in portal interface "
                            f"(one of {', '.join(PORTAL_OPT_IN)}; the safe set needs no entry)")
    return name


def check_dbus_name(name, key="dbus_filter"):
    """A D-Bus name an app may be allowed to talk to; refuses names that hand over the host."""
    _match(name, DBUS_NAME_RE, f"permissions.{key} entry")
    base, wild = (name[:-2], True) if name.endswith(".*") else (name, False)
    if wild and base.count(".") + 1 < DBUS_MIN_WILDCARD_PARTS:
        raise ManifestError(f"{key} entry {name!r}: a wildcard needs at least {DBUS_MIN_WILDCARD_PARTS} name parts before '.*'")
    for blocked in DBUS_BLOCKED:
        hit = base == blocked or base.startswith(blocked + ".") or (wild and blocked.startswith(base + "."))
        if hit:
            raise ManifestError(f"{key} entry {name!r} is refused: it reaches {blocked}, which can control the host or the desktop")
    return name


def check_dbus_own(name):
    """A D-Bus name an app may own: like a talk name, and never inside a desktop service namespace."""
    check_dbus_name(name, "dbus_own")
    base = name[:-2] if name.endswith(".*") else name
    if base.startswith(DBUS_OWN_OK):
        return name
    if (base + ".").startswith(DBUS_NO_OWN) or any(n.startswith(base + ".") for n in DBUS_NO_OWN):
        raise ManifestError(f"dbus_own entry {name!r} is refused: owning a name in a desktop service namespace "
                            "would let the app impersonate that service")
    return name


# Paths below the home directory (no leading "~/") that hold credentials or secrets: never granted.
SECRET_HOME_DIRS = (".ssh", ".gnupg", ".aws", ".kube", ".docker", ".password-store", ".netrc", ".config/gcloud",
                    ".config/gh", ".config/Bitwarden", ".local/share/keyrings", ".local/share/gnome-keyring",
                    ".git-credentials", ".pki", ".bash_history", ".zsh_history", ".zhistory", ".python_history",
                    ".lesshst", ".psql_history", ".mysql_history", ".node_repl_history", ".local/share/fish",
                    ".mozilla", ".thunderbird", ".mail", ".gnupg2", ".var", ".config/google-chrome",
                    ".config/chromium", ".config/BraveSoftware", ".config/vivaldi", ".config/microsoft-edge",
                    ".config/opera", ".config/mozilla", ".cache/mozilla", ".local/share/kwalletd", ".local/share/Trash")
# Name patterns of password databases, wherever they sit below the home directory.
SECRET_SUFFIXES = (".kdbx", ".kdb", ".key", ".pem", ".p12", ".pfx")
# Too broad: they contain the secrets of other applications and the persistence locations below.
BROAD_HOME_DIRS = (".config", ".local", ".local/share", ".local/state", ".cache")
# Writable access would let the app run code outside the jail later (login, shell, desktop, systemd).
PERSIST_HOME_DIRS = (".local/bin", ".config/autostart", ".config/systemd", ".config/environment.d", ".config/fish",
                     ".local/share/applications", ".local/share/systemd", ".local/share/dbus-1", ".bashrc.d",
                     ".profile.d", ".config/plasma-workspace", ".config/Code", ".config/nvim", ".config/zsh")
# Single files that run code outside the jail at login or shell start; never granted read-write.
PERSIST_HOME_FILES = (".bashrc", ".bash_profile", ".bash_login", ".bash_logout", ".profile", ".zshrc", ".zshenv", ".zprofile",
                      ".zlogin", ".xprofile", ".xinitrc", ".xsession", ".xsessionrc", ".pam_environment", ".gitconfig", ".npmrc",
                      ".pypirc", ".netrc", ".vimrc", ".config/git/config")
# System trees that are never user data; the jail provides its own /dev, /proc, /run and /etc.
SYSTEM_PATHS = ("/etc", "/dev", "/proc", "/sys", "/run", "/boot", "/root", "/usr", "/bin", "/sbin", "/lib", "/lib32",
                "/lib64")


def _within(path, base):
    return path == base or path.startswith(base + "/")


def sensitive_reason(path, mode):
    """Why a normalized dirs path (``~/x`` or absolute) must not be granted in this mode, else None.

    Home-relative rules apply to ``~/x`` paths; callers that resolved symlinks pass the real path
    relative to the real home as ``~/x`` so a link cannot dodge them.
    """
    if path.startswith("~/"):
        rel = path[2:].strip("/")
        for d in SECRET_HOME_DIRS:
            if _within(rel, d):
                return f"~/{d} holds credentials or secrets"
        if rel.lower().endswith(SECRET_SUFFIXES):
            return "files like this hold credentials or secrets (password databases, private keys)"
        for d in BROAD_HOME_DIRS:
            if rel == d:
                return f"~/{d} is too broad: it contains the data of every other application"
        if mode == "rw":
            if rel in PERSIST_HOME_FILES:
                return f"write access to ~/{rel} could plant code that runs outside the jail (login, shell or tool startup)"
            for d in PERSIST_HOME_DIRS:
                if _within(rel, d) or (rel and _within(d, rel)):
                    return f"write access to ~/{rel} could plant code that runs outside the jail (login, shell or desktop startup)"
        return None
    for d in SYSTEM_PATHS:
        if _within(path, d):
            return f"{d} is a system tree and is not available to jailed apps"
    return None


def _check_dir(entry):
    path, _, mode = entry.partition(":")
    if mode not in ("", "ro", "rw"):
        raise ManifestError(f"dirs entry {entry!r}: mode must be ro or rw")
    if not (path.startswith("/") or path.startswith("~/")):
        raise ManifestError(f"dirs entry {entry!r}: path must be absolute or start with ~/")
    if path in ("/", "~/") or ".." in path.split("/"):
        raise ManifestError(f"dirs entry {entry!r}: path is too broad or contains '..'")
    reason = sensitive_reason(path.rstrip("/") or path, mode)
    if reason:
        raise ManifestError(f"dirs entry {entry!r} is refused: {reason}")
    return entry


def normalize_dir(spec, home, cwd):
    """Canonical `permissions.dirs` entry for a user-typed PATH[:ro|:rw].

    Relative paths resolve against cwd; paths below home become `~/...`. No symlinks are resolved.
    """
    path, mode = spec, ""
    if spec.endswith((":ro", ":rw")):
        path, mode = spec[:-3], spec[-3:]
    if not path:
        raise ManifestError("directory path is empty")
    if path.startswith("~/"):
        path = os.path.join(str(home), path[2:])
    path = os.path.normpath(os.path.join(str(cwd), path))
    home = os.path.normpath(str(home))
    if path == home or home.startswith(path.rstrip(os.sep) + os.sep) or path == os.sep:
        raise ManifestError("the home directory itself (or a parent of it) cannot be granted")
    if path.startswith(home + os.sep):
        path = "~/" + path[len(home) + 1:]
    entry = path + (":rw" if mode == ":rw" else "")
    return _check_dir(_text(entry, "directory"))


def merge_dirs(base, extra):
    """Union of two dirs lists keyed by path; read-write wins over read-only."""
    merged = {}
    for entry in (*base, *extra):
        path, _, mode = entry.partition(":")
        if merged.get(path) != "rw":
            merged[path] = "rw" if mode == "rw" else ""
    return tuple(p + (":rw" if m else "") for p, m in merged.items())


def _unknown(table, allowed, where):
    extra = sorted(set(table) - allowed)
    if extra:
        raise ManifestError(f"unknown key(s) in {where}: {', '.join(map(str, extra))}")


def _portal_consistency(p):
    if p.portal_interfaces and not p.portals:
        raise ManifestError("permissions.portal_interfaces needs portals = true")


def _permissions(table):
    if not isinstance(table, dict):
        raise ManifestError("permissions must be a table")
    _unknown(table, PERM_KEYS, "[permissions]")
    perms = {}
    for key in ("network", "audio", "gpu", "portals", "userns"):
        if key in table:
            perms[key] = _bool(table[key], f"permissions.{key}")
    if "display" in table:
        if table["display"] not in DISPLAYS:
            raise ManifestError(f"permissions.display must be one of {', '.join(DISPLAYS)}")
        perms["display"] = table["display"]
    if "dbus_filter" in table:
        names = _str_list(table["dbus_filter"], "permissions.dbus_filter")
        for n in names:
            check_dbus_name(n)
        perms["dbus_filter"] = tuple(names)
    if "dbus_own" in table:
        perms["dbus_own"] = tuple(check_dbus_own(n) for n in _str_list(table["dbus_own"], "permissions.dbus_own"))
    if "portal_interfaces" in table:
        names = _str_list(table["portal_interfaces"], "permissions.portal_interfaces")
        perms["portal_interfaces"] = tuple(check_portal_interface(n) for n in names)
    if "dirs" in table:
        perms["dirs"] = tuple(_check_dir(d) for d in _str_list(table["dirs"], "permissions.dirs"))
    _portal_consistency(Permissions(**perms))
    return Permissions(**perms)


def _published_at(value):
    _match(value, PUBLISHED_RE, "published_at")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        raise ManifestError(f"published_at is not a valid date: {value!r}") from e
    return value


def validate(m):
    """Return m after checking every field; raise ManifestError otherwise."""
    _match(m.name, NAME_RE, "name")
    _match(m.source, SOURCE_RE, "source")
    _text(m.asset_pattern, "asset_pattern")
    if "/" in m.asset_pattern:
        raise ManifestError("asset_pattern must not contain '/'")
    _text(m.version, "version", 128)
    _match(m.sha256, SHA256_RE, "sha256")
    if type(m.evidence_tier) is not int or m.evidence_tier not in TIERS:
        raise ManifestError(f"evidence_tier must be one of {TIERS}")
    _published_at(m.published_at)
    if m.owner_id is not None and (type(m.owner_id) is not int or m.owner_id < 1):
        raise ManifestError("owner_id must be a positive integer")
    if m.channel not in CHANNELS:
        raise ManifestError(f"channel must be one of {', '.join(CHANNELS)}")
    p = m.permissions
    for key in ("network", "audio", "gpu", "portals", "userns"):
        _bool(getattr(p, key), f"permissions.{key}")
    if p.display not in DISPLAYS:
        raise ManifestError(f"permissions.display must be one of {', '.join(DISPLAYS)}")
    for n in p.dbus_filter:
        check_dbus_name(n)
    for n in p.dbus_own:
        check_dbus_own(n)
    for n in p.portal_interfaces:
        check_portal_interface(n)
    _portal_consistency(p)
    for d in p.dirs:
        _check_dir(_text(d, "permissions.dirs entry"))
    return m


def loads(text):
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"invalid TOML: {e}") from e
    _unknown(data, TOP_KEYS, "manifest")
    if data.get("schema") != SCHEMA_VERSION:
        raise ManifestError(f"schema must be {SCHEMA_VERSION}")
    missing = sorted(TOP_KEYS - {"permissions", "owner_id", "channel", "schema"} - set(data))
    if missing:
        raise ManifestError(f"missing key(s): {', '.join(missing)}")
    return validate(Manifest(
        name=data["name"], source=data["source"], asset_pattern=data["asset_pattern"],
        version=data["version"], sha256=data["sha256"], evidence_tier=data["evidence_tier"],
        published_at=data["published_at"], owner_id=data.get("owner_id"), channel=data.get("channel", "stable"), permissions=_permissions(data.get("permissions", {})),
    ))


def load(path):
    return loads(Path(path).read_text(encoding="utf-8"))


def _quote(s):
    out = ['"']
    for ch in s:
        if ch == '"' or ch == "\\":
            out.append("\\" + ch)
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _array(items):
    return "[" + ", ".join(_quote(i) for i in items) + "]"


def dumps(m):
    """Deterministic TOML for a validated manifest."""
    validate(m)
    p = m.permissions
    lines = [
        f"schema = {SCHEMA_VERSION}",
        f"name = {_quote(m.name)}",
        f"source = {_quote(m.source)}",
        f"asset_pattern = {_quote(m.asset_pattern)}",
        f"version = {_quote(m.version)}",
        f"sha256 = {_quote(m.sha256)}",
        f"evidence_tier = {m.evidence_tier}",
        f"published_at = {_quote(m.published_at)}",
        *([f"owner_id = {m.owner_id}"] if m.owner_id is not None else []),
        *([f"channel = {_quote(m.channel)}"] if m.channel != "stable" else []),
        "",
        "[permissions]",
        f"network = {str(p.network).lower()}",
        f"audio = {str(p.audio).lower()}",
        f"gpu = {str(p.gpu).lower()}",
        f"display = {_quote(p.display)}",
        f"dbus_filter = {_array(p.dbus_filter)}",
        f"dbus_own = {_array(p.dbus_own)}",
        f"portals = {str(p.portals).lower()}",
        f"portal_interfaces = {_array(p.portal_interfaces)}",
        f"userns = {str(p.userns).lower()}",
        f"dirs = {_array(p.dirs)}",
        "",
    ]
    return "\n".join(lines)


def dump(path, m):
    """Write atomically (temp file in the same directory, then rename)."""
    path = Path(path)
    text = dumps(m)
    tmp = path.with_name(f".{path.name}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
