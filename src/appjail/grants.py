# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""What an app may be granted: D-Bus names, portal interfaces and directories. Pure policy, no I/O."""

import os
import re

from .valid import ManifestError, match, string

DBUS_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*)+(\.\*)?")

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
    match(name, DBUS_NAME_RE, f"permissions.{key} entry")
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
    base = name.removesuffix(".*")
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


def check_dir(entry):
    path, _, mode = entry.partition(":")
    if mode not in ("", "ro", "rw"):
        raise ManifestError(f"dirs entry {entry!r}: mode must be ro or rw")
    if not (path.startswith(("/", "~/"))):
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
    return check_dir(string(entry, "directory"))


def split_file_mode(spec):
    """(path, "rw" or "") for a PATH, PATH:ro or PATH:rw file argument."""
    if spec.endswith(":rw"):
        return spec[:-3], "rw"
    return (spec.removesuffix(":ro")), ""


def merge_dirs(base, extra):
    """Union of two dirs lists keyed by path; read-write wins over read-only."""
    merged = {}
    for entry in (*base, *extra):
        path, _, mode = entry.partition(":")
        if merged.get(path) != "rw":
            merged[path] = "rw" if mode == "rw" else ""
    return tuple(p + (":rw" if m else "") for p, m in merged.items())
