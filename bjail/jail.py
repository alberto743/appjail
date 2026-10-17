# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""bwrap argument builders and runners. Every untrusted step runs through here.

Argument builders are pure functions so they can be unit-tested without bwrap.
"""

import os
import shutil
import subprocess
from pathlib import Path

FETCHER = Path(__file__).with_name("fetcher.py")
SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64")
ETC_FILES = ("/etc/hosts", "/etc/nsswitch.conf", "/etc/host.conf", "/etc/gai.conf", "/etc/localtime")
ETC_DIRS = ("/etc/ssl", "/etc/ca-certificates")
SAFE_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}


class JailError(Exception):
    pass


def find_bwrap():
    path = shutil.which("bwrap")
    if not path:
        raise JailError("bwrap (bubblewrap) is not installed")
    return path


def system_args():
    """Read-only system: merged-usr symlinks are recreated, real dirs are bind-mounted."""
    args = []
    for d in SYSTEM_DIRS:
        if os.path.islink(d):
            args += ["--symlink", os.readlink(d), d]
        elif os.path.isdir(d):
            args += ["--ro-bind", d, d]
    return args


def etc_args():
    args = []
    for f in ETC_FILES:
        if os.path.exists(f):
            args += ["--ro-bind", os.path.realpath(f), f]
    for d in ETC_DIRS:
        if os.path.isdir(d):
            args += ["--ro-bind", d, d]
    # resolv.conf is usually a symlink into /run; bind its content, not the link.
    if os.path.exists("/etc/resolv.conf"):
        args += ["--ro-bind", os.path.realpath("/etc/resolv.conf"), "/etc/resolv.conf"]
    return args


def common_args():
    args = ["--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv"]
    for k, v in SAFE_ENV.items():
        args += ["--setenv", k, v]
    return args + system_args() + ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]


def download_args(stage_dir, command, fetcher=FETCHER):
    """Network-only jail: no host files except the read-only fetcher and the staging dir."""
    return (common_args() + ["--share-net"] + etc_args()
            + ["--ro-bind", str(fetcher), "/fetcher.py", "--bind", str(stage_dir), "/stage"]
            + ["--remount-ro", "/", "--chdir", "/stage", "--"] + command)


def run(args, timeout=1800):
    """Run bwrap with a minimal host environment; returns CompletedProcess (text, captured)."""
    try:
        return subprocess.run([find_bwrap(), *args], capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin"})
    except subprocess.TimeoutExpired as e:
        raise JailError("jailed command timed out") from e


def download(url, stage_dir, filename, expected_size):
    """Download url into stage_dir/filename inside the network-only jail."""
    cmd = ["/usr/bin/python3", "-I", "/fetcher.py", url, f"/stage/{filename}", str(int(expected_size))]
    proc = run(download_args(stage_dir, cmd))
    if proc.returncode != 0:
        from .textsafe import clean
        raise JailError("download failed: " + clean(proc.stderr.strip() or f"exit {proc.returncode}", 400))
    return Path(stage_dir) / filename
