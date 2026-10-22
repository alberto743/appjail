# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Desktop portals (file chooser, notifications, ...) for an app in the jail.

xdg-desktop-portal decides who is calling from the D-Bus peer's process: it reads
`/proc/<pid>/root/.flatpak-info` and `$XDG_RUNTIME_DIR/.flatpak/<instance>/bwrapinfo.json`. Those
two files are the only "sandbox identity" the portal understands besides Snap and Linyaps, so appjail
writes them in that format. This is a compatibility shim: nothing here depends on or installs
Flatpak. Side effect to know about: the portal's permission store and Background portal treat the app
as a Flatpak app (an autostart entry would say `flatpak run`, which is inert without Flatpak).

The identity is bound into the jail of the xdg-dbus-proxy, whose connection is the peer the portal
sees, never into the app's jail: the app can neither read nor forge it, and cannot pick its own app id
(the alternative, `org.freedesktop.host.portal.Registry`, lets an app claim any id).
"""

import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path

from . import grants
from .jail import RunError

ID_PREFIX = "app.appjail."
APP_ID_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){2,}")
PORTAL_NAME = "org.freedesktop.portal.Desktop"
DOCUMENTS_NAME = "org.freedesktop.portal.Documents"
PORTAL_PATH = "/org/freedesktop/portal/desktop"


def app_id(name):
    """Valid reverse-DNS application id for an installed app name (`[a-z0-9][a-z0-9._-]*`)."""
    parts = []
    for part in re.split(r"\.+", name):
        part = re.sub(r"[^A-Za-z0-9]", "_", part) or "_"
        parts.append(("x" + part) if part[0].isdigit() else part)
    result = ID_PREFIX + ".".join(parts)
    if not APP_ID_RE.fullmatch(result):
        raise RunError(f"cannot derive a portal application id from {name!r}")
    return result


def interfaces(perms):
    """Portal interfaces the app may call: the safe set, plus its opt-ins."""
    if not perms.portals:
        return ()
    return grants.PORTAL_SAFE + tuple(perms.portal_interfaces)


def identity_file(app, instance, network=False):
    """Text of `.flatpak-info`: the minimum the portal requires, and nothing about the host."""
    return ("[Application]\n"
            f"name={app}\n\n"
            "[Instance]\n"
            f"instance-id={instance}\n\n"
            "[Context]\n"
            + ("shared=network;\n" if network else ""))


def proxy_rules(perms):
    """xdg-dbus-proxy options for the portal part of the filter (appended to the name rules)."""
    names = interfaces(perms)
    if not names:
        return []
    rules = [f"--call={PORTAL_NAME}=org.freedesktop.portal.{i}.*@{PORTAL_PATH}" for i in names]
    rules += [f"--call={PORTAL_NAME}=org.freedesktop.portal.Request.*@{PORTAL_PATH}/request/*",
              f"--call={PORTAL_NAME}=org.freedesktop.portal.Session.*@{PORTAL_PATH}/session/*",
              f"--call={PORTAL_NAME}=org.freedesktop.DBus.Properties.*@{PORTAL_PATH}",
              f"--call={PORTAL_NAME}=org.freedesktop.DBus.Introspectable.*@{PORTAL_PATH}",
              f"--talk={DOCUMENTS_NAME}",
              f"--broadcast={PORTAL_NAME}=org.freedesktop.portal.*@{PORTAL_PATH}/*"]
    return rules


def activate_documents(host_env, timeout=5.0):
    """Ask the session bus to start the document portal (it is D-Bus activated, so it may not run yet)."""
    rt = host_env.get("XDG_RUNTIME_DIR", "")
    dbus_send = "/usr/bin/dbus-send"
    if not rt or not os.access(dbus_send, os.X_OK):
        return
    env = {"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": rt}
    if host_env.get("DBUS_SESSION_BUS_ADDRESS"):
        env["DBUS_SESSION_BUS_ADDRESS"] = host_env["DBUS_SESSION_BUS_ADDRESS"]
    try:
        subprocess.run([dbus_send, "--session", "--print-reply", f"--reply-timeout={int(timeout * 1000)}",
                        f"--dest={DOCUMENTS_NAME}", "/org/freedesktop/portal/documents",
                        "org.freedesktop.portal.Documents.GetMountPoint"],
                       env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout + 2)
    except (OSError, subprocess.SubprocessError):
        pass


def doc_dir(runtime_dir, app, host_env=None):
    """The document portal's per-app view, which the app gets as $XDG_RUNTIME_DIR/doc."""
    path = Path(runtime_dir) / "doc" / "by-app" / app
    if not path.is_dir() and host_env is not None:
        activate_documents(host_env)
    if not path.is_dir():
        raise RunError("the document portal is not running (no " + str(path) + "); portals need "
                       "xdg-desktop-portal and its document portal, normally started by the desktop session")
    return path


STORE_NAME = "org.freedesktop.impl.portal.PermissionStore"
STORE_PATH = "/org/freedesktop/impl/portal/PermissionStore"
DOC_PERMISSIONS = ("read", "write", "grant-permissions", "delete")
DOC_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def bus_call(host_env, dest, path, member, *args, timeout=10.0):
    """Call a method on the host session bus (`dbus-send`, the same way as `activate_documents`)."""
    rt = host_env.get("XDG_RUNTIME_DIR", "")
    dbus_send = "/usr/bin/dbus-send"
    if not rt or not os.access(dbus_send, os.X_OK):
        raise RunError("dbus-send is needed to reach the portals (package dbus-bin)")
    env = {"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": rt}
    if host_env.get("DBUS_SESSION_BUS_ADDRESS"):
        env["DBUS_SESSION_BUS_ADDRESS"] = host_env["DBUS_SESSION_BUS_ADDRESS"]
    try:
        r = subprocess.run([dbus_send, "--session", "--print-reply", f"--reply-timeout={int(timeout * 1000)}",
                            f"--dest={dest}", path, member, *args],
                           env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout + 2)
    except (OSError, subprocess.SubprocessError) as e:
        raise RunError(f"cannot reach the portals: {e}") from e
    if r.returncode != 0:
        raise RunError("the portal refused the call: " + (r.stderr.strip().splitlines() or ["?"])[-1])
    return r.stdout


def store_call(host_env, method, *args):
    return bus_call(host_env, STORE_NAME, STORE_PATH, f"{STORE_NAME}.{method}", *args)


def granted_documents(app, host_env):
    """Document ids the document portal has granted to this app id, with the permissions, sorted."""
    ids = re.findall(r'^\s*string "([^"]*)"\s*$', store_call(host_env, "List", "string:documents"), re.MULTILINE)
    found = {}
    for doc in ids:
        if not DOC_ID_RE.fullmatch(doc):
            continue
        reply = store_call(host_env, "Lookup", "string:documents", f"string:{doc}")
        m = re.search(r'dict entry\(\s*string "' + re.escape(app) + r'"\s*array \[(.*?)\]', reply, re.DOTALL)
        perms = re.findall(r'string "([^"]*)"', m.group(1)) if m else []
        if perms:
            found[doc] = perms
    return dict(sorted(found.items()))


def revoke_documents(app, host_env, ids):
    """Remove this app id's permissions on each document; other apps' grants and the document are untouched.

    This goes through the document portal, not the permission store: the portal keeps its own copy and
    would keep serving the file after a store-only change (verified against the real portal).
    """
    for doc in ids:
        bus_call(host_env, DOCUMENTS_NAME, "/org/freedesktop/portal/documents",
                 "org.freedesktop.portal.Documents.RevokePermissions",
                 f"string:{doc}", f"string:{app}", "array:string:" + ",".join(DOC_PERMISSIONS))


class Instance:
    """One running app's portal identity: `.flatpak/<id>/{info,bwrapinfo.json}` in the host runtime dir."""

    def __init__(self, runtime_dir, app, network=False):
        self.runtime_dir, self.app, self.network = Path(runtime_dir), app, network
        self.id = str(secrets.randbelow(10**15) + 10**14)
        self.dir = self.runtime_dir / ".flatpak" / self.id

    def __enter__(self):
        self.dir.parent.mkdir(mode=0o700, exist_ok=True)
        self.dir.mkdir(mode=0o700)
        info = self.dir / "info"
        info.write_text(identity_file(self.app, self.id, self.network), encoding="utf-8")
        os.chmod(info, 0o444)
        self.info = info
        return self

    def child_started(self, pid):
        """Publish the app jail's init pid, as bwrap's status reports it; the portal needs it."""
        tmp = self.dir / "bwrapinfo.json.tmp"
        tmp.write_text(json.dumps({"child-pid": int(pid)}), encoding="utf-8")
        os.replace(tmp, self.dir / "bwrapinfo.json")

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)
        try:
            self.dir.parent.rmdir()
        except OSError:
            pass
