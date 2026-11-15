# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""What an app may be granted: D-Bus names, portal interfaces, directories and environment variables. Pure policy, no I/O."""

import os
import re

from .valid import ManifestError, match, string

DBUS_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*)+(\.\*)?")

# Talking to these on the session bus is equivalent to running commands on the host or taking over
# the desktop, so a filter that allows them would not be a filter. Refused, never granted.
DBUS_BLOCKED = ("org.freedesktop.DBus", "org.freedesktop.systemd1", "org.freedesktop.Flatpak",
                "org.freedesktop.impl", "org.gnome.Shell", "org.gnome.SessionManager", "org.kde.KWin",
                "org.kde.klauncher5", "org.kde.klauncher6", "org.freedesktop.portal", "ca.desrt.dconf", "org.gtk.vfs",
                # measured (docs/compositor-assessment): Mutter's ScreenCast, RemoteDesktop and InputCapture open a session for
                # any client of the bus, so these names are the only thing between an app and the screen or the keyboard
                "org.gnome.Mutter", "org.freedesktop.a11y", "org.gnome.ScreenSaver",
                "org.kde.kglobalaccel", "org.kde.keyboard",
                # measured on Muffin 6.4: its DisplayConfig answers any client and can apply a monitor layout, the backlight and
                # the gamma ramps
                "org.cinnamon.Muffin",
                # measured on Cinnamon 6.4: its Eval runs any JavaScript in the shell for any client (a command, typing into
                # other windows); the shell also answers org.gnome.Shell.Screenshot, refused above
                "org.Cinnamon",
                # measured on Cinnamon 6.8, which renamed GNOME's screenshot name: org.cinnamon.Screenshot writes a picture of the
                # whole screen for any client, and org.cinnamon.ScreenSaver locks, unlocks and ends the screensaver
                "org.cinnamon.Screenshot", "org.cinnamon.ScreenSaver",
                # measured on Plasma 6.3 and 6.6: the shell's evaluateScript runs a desktop script for any client (it writes
                # the user's configuration files), and klipper, in the same process, hands over the clipboard and its history
                "org.kde.plasmashell", "org.kde.klipper")
DBUS_SENSITIVE = ("org.freedesktop.secrets", "org.gnome.keyring", "org.kde.kwalletd5", "org.kde.kwalletd6")
DBUS_MIN_WILDCARD_PARTS = 3
# Owning a name lets the app be the service behind it. Impersonating a desktop service (notifications, secrets,
# polkit, the file manager, ...) would let the app intercept what other apps send there, so the desktop
# namespaces cannot be owned, except the status-notifier names an app registers for its own tray icon.
DBUS_NO_OWN = ("org.freedesktop.", "org.gnome.", "org.kde.", "org.a11y.", "com.canonical.", "org.ayatana.",
               "org.gtk.", "ca.desrt.")
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


# Environment variables of the manifest's [env] table.
ENV_NAME_RE = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")
ENV_MAX_ENTRIES = 32
ENV_MAX_VALUE = 1024
# Names appjail sets itself (the display, bus, audio and portal ones depend on the permissions): only the permissions
# change them.
ENV_REFUSED = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TZ", "XDG_RUNTIME_DIR", "APPDIR", "APPIMAGE_EXTRACT_AND_RUN",
               "TMPDIR", "DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "GDK_BACKEND", "QT_QPA_PLATFORM", "MOZ_ENABLE_WAYLAND",
               "ELECTRON_OZONE_PLATFORM_HINT", "SDL_VIDEODRIVER", "DBUS_SESSION_BUS_ADDRESS", "PULSE_SERVER", "GTK_USE_PORTAL")
# Names that make the dynamic loader or an interpreter load code of the caller's choosing.
ENV_REFUSED_HOOKS = ("BASH_ENV", "ENV", "NODE_OPTIONS")
ENV_REFUSED_PREFIXES = ("LD_", "PYTHON", "PERL5")


def check_env(key, value):
    """One entry of [env]: a plain name that appjail does not set, and a short text value."""
    match(key, ENV_NAME_RE, "env name")
    if key in ENV_REFUSED or key in ENV_REFUSED_HOOKS or key.startswith(ENV_REFUSED_PREFIXES):
        raise ManifestError(f"env name {key} is refused: appjail sets it from the permissions, or it makes a program "
                            "load code of the app's choosing")
    if not isinstance(value, str):
        raise ManifestError(f"env {key} must be a string")
    if value:
        string(value, f"env {key}", ENV_MAX_VALUE)
    return key, value


def check_env_table(pairs):
    """The whole [env] table, as (name, value) pairs: valid, without duplicates, at most ENV_MAX_ENTRIES."""
    if len(pairs) > ENV_MAX_ENTRIES:
        raise ManifestError(f"env has more than {ENV_MAX_ENTRIES} entries")
    names = [check_env(k, v)[0] for k, v in pairs]
    if len(set(names)) != len(names):
        raise ManifestError("env names must be unique")
    return pairs


# Paths below the home directory (no leading "~/") that hold credentials or secrets: never granted.
SECRET_HOME_DIRS = (".ssh", ".gnupg", ".aws", ".kube", ".docker", ".password-store", ".netrc", ".config/gcloud",
                    ".config/gh", ".config/Bitwarden", ".local/share/keyrings", ".local/share/gnome-keyring",
                    ".git-credentials", ".pki", ".bash_history", ".zsh_history", ".zhistory", ".python_history",
                    ".lesshst", ".psql_history", ".mysql_history", ".node_repl_history", ".local/share/fish",
                    ".mozilla", ".thunderbird", ".mail", ".gnupg2", ".var", ".config/google-chrome",
                    ".config/chromium", ".config/BraveSoftware", ".config/vivaldi", ".config/microsoft-edge",
                    ".config/opera", ".config/mozilla", ".cache/mozilla", ".local/share/kwalletd", ".local/share/Trash",
                    # package-registry and cloud tokens, and tools that hold a password vault or a messaging session
                    ".npmrc", ".yarnrc", ".yarnrc.yml", ".pypirc", ".cargo/credentials", ".cargo/credentials.toml",
                    ".gem/credentials", ".m2/settings.xml", ".gradle/gradle.properties", ".config/rclone", ".azure",
                    ".oci", ".config/doctl", ".config/hub", ".config/glab-cli", ".terraform.d", ".config/op",
                    ".config/1Password", ".1password", ".config/keepassxc", ".local/share/keepassxc", ".config/KeePass",
                    ".config/Signal")
# Name patterns of password databases, wherever they sit below the home directory.
SECRET_SUFFIXES = (".kdbx", ".kdb", ".key", ".pem", ".p12", ".pfx")
# Too broad: they contain the secrets of other applications and the persistence locations below.
BROAD_HOME_DIRS = (".config", ".local", ".local/share", ".local/state", ".cache")
# Writable access would let the app run code outside the jail later (login, shell, desktop, systemd, the Python user
# site that every host Python, appjail included, imports, thumbnailers and file-manager actions). The icon themes are
# here too: the desktop decodes their images outside any jail, and appjail runs gtk-update-icon-cache on them.
PERSIST_HOME_DIRS = (".local/bin", ".config/autostart", ".config/systemd", ".config/environment.d", ".config/fish",
                     ".local/share/applications", ".local/share/systemd", ".local/share/dbus-1", ".bashrc.d",
                     ".profile.d", ".config/plasma-workspace", ".config/Code", ".config/nvim", ".config/zsh",
                     ".local/lib", ".local/share/thumbnailers", ".local/share/kio/servicemenus",
                     ".local/share/kservices5", ".local/share/nautilus/scripts", ".local/share/nemo/actions",
                     ".local/share/nemo/scripts", ".local/share/icons", ".icons")
# Writable access would let the app change what the desktop's own apps show or decode outside the jail: GTK settings
# and style sheets (gtk.css, applied to every GTK app of the user), KDE and Qt style settings, themes, fonts (parsed by the host's font loaders)
# and the fontconfig configuration. Not code, but a way to spoof the interface of other apps or reach a parser outside
# any jail. Read-only grants stay possible, to share the look.
APPEARANCE_HOME_DIRS = (".config/gtk-2.0", ".gtkrc-2.0", ".config/gtk-3.0", ".config/gtk-4.0", ".local/share/themes",
                        ".themes", ".config/fontconfig", ".local/share/fonts", ".fonts", ".config/kdeglobals",
                        ".config/qt5ct", ".config/qt6ct", ".config/Kvantum")
# Single files that run code outside the jail at login or shell start; never granted read-write.
PERSIST_HOME_FILES = (".bashrc", ".bash_profile", ".bash_login", ".bash_logout", ".profile", ".zshrc", ".zshenv", ".zprofile",
                      ".zlogin", ".xprofile", ".xinitrc", ".xsession", ".xsessionrc", ".pam_environment", ".gitconfig", ".npmrc",
                      ".pypirc", ".netrc", ".vimrc", ".config/git/config")
# System trees that are never user data; the jail provides its own /dev, /proc, /run and /etc.
SYSTEM_PATHS = ("/etc", "/dev", "/proc", "/sys", "/run", "/boot", "/root", "/usr", "/bin", "/sbin", "/lib", "/lib32",
                "/lib64")
# Shared by every program and full of their sockets (X11, tmux, ssh-agent, ...). A bind mount does not stop connect(),
# even read-only, so granting such a directory would reach those programs from inside the jail. Only directories are
# refused: a single regular file there (a download opened from /tmp) carries no socket.
SHARED_DIRS = ("/tmp", "/var/tmp")


# udisks mounts removable media of a user at /run/media/USER/LABEL (Fedora, Arch; Debian and Ubuntu use /media/USER/LABEL).
# Those mount points are the one exception to refusing /run. Entries are checked where the user is not known (a manifest,
# a typed path) with ANY_USER, and at launch with the name of the user running the app.
ANY_USER = "*"
REMOVABLE_MEDIA = "/run/media/USER/LABEL"  # the exception, as the reference prints it


def _removable_media(path, media_user):
    """True for a mount point of removable media, or a path below one, in the directory udisks keeps for ``media_user``."""
    parts = path.split("/")
    return bool(media_user and len(parts) >= 5 and parts[:3] == ["", "run", "media"] and parts[3] and parts[4]
                and media_user in (ANY_USER, parts[3]))


def _within(path, base):
    return path == base or path.startswith(base + "/")


def sensitive_reason(path, mode, media_user=None):
    """Why a normalized dirs path (``~/x`` or absolute) must not be granted in this mode, else None.
    ``media_user`` is the user whose removable media under /run/media may be granted (ANY_USER: whoever's); None: nobody's.

    Home-relative rules apply to ``~/x`` paths; callers that resolved symlinks pass the real path
    relative to the real home as ``~/x`` so a link cannot dodge them.
    """
    if path.startswith("~/"):
        rel = path[2:].strip("/")
        for d in SECRET_HOME_DIRS:
            if _within(rel, d):
                return f"~/{d} holds credentials or secrets"
            if rel and _within(d, rel):
                return f"~/{rel} contains ~/{d}, which holds credentials or secrets; grant a subdirectory"
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
            for d in APPEARANCE_HOME_DIRS:
                if _within(rel, d) or (rel and _within(d, rel)):
                    return (f"write access to ~/{rel} could change how your other apps look, or plant files the desktop "
                            "decodes outside the jail (toolkit settings, themes, fonts)")
        return None
    for d in SYSTEM_PATHS:
        if _within(path, d):
            if d == "/run" and _removable_media(path, media_user):
                continue
            return f"{d} is a system tree and is not available to jailed apps"
    return None


def directory_reason(path, mode, media_user=None):
    """Why a directory grant (normalized like sensitive_reason's path) must be refused, else None: the sensitive-path
    policy plus the shared directories, which only matter for a directory."""
    for d in SHARED_DIRS:
        if _within(path, d):
            return (f"{d} is shared by every program and holds their sockets (X11, tmux, ...), which the app could "
                    "reach even read-only; use a directory elsewhere")
    return sensitive_reason(path, mode, media_user)


def check_dir(entry):
    path, _, mode = entry.partition(":")
    if mode not in ("", "ro", "rw"):
        raise ManifestError(f"dirs entry {entry!r}: mode must be ro or rw")
    if not (path.startswith(("/", "~/"))):
        raise ManifestError(f"dirs entry {entry!r}: path must be absolute or start with ~/")
    if path in ("/", "~/") or ".." in path.split("/"):
        raise ManifestError(f"dirs entry {entry!r}: path is too broad or contains '..'")
    if os.path.normpath(path) != path.rstrip("/"):
        raise ManifestError(f"dirs entry {entry!r}: path is not normalised (no '.', empty or repeated components)")
    reason = directory_reason(path.rstrip("/") or path, mode, ANY_USER)
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
    if ":" in path:
        raise ManifestError("a directory path with ':' in it cannot be granted (':' separates the mode)")
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
