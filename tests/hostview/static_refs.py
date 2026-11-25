# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Host paths and host programs an extracted AppImage names in its files (guest only; not run by pytest).

Usage: static_refs.py ROOT...   For each tree: the paths under /usr (bin, sbin, libexec, lib, share) and /etc, and the
program names from a fixed list of helpers that desktop software is known to run, that appear as text in any file. A name in
a file does not mean the program runs: it is where a dynamic trace should look.
"""

import re
import sys
from collections import Counter
from pathlib import Path

PATHS = re.compile(rb"/(?:usr/(?:local/)?(?:s?bin|libexec|lib(?:64)?|share|etc)|etc|var|opt|bin|sbin)/[A-Za-z0-9._+@/-]{2,80}")
HELPERS = (b"xdg-open", b"xdg-mime", b"xdg-settings", b"xdg-email", b"gio", b"gvfs", b"dbus-launch", b"dbus-send",
           b"update-mime-database", b"gtk-update-icon-cache", b"fc-cache", b"ldconfig", b"lsof", b"strace", b"ps",
           b"gs", b"ghostscript", b"lpr", b"lp", b"cups", b"sendmail", b"notify-send", b"zenity", b"kdialog",
           b"gnome-open", b"kde-open", b"sensible-browser", b"x-www-browser", b"firefox", b"gsettings", b"dconf",
           b"pkexec", b"sudo", b"bash", b"python3", b"perl", b"curl", b"wget", b"convert", b"magick", b"display")


def scan(root):
    paths, helpers = Counter(), Counter()
    word = {h: re.compile(rb"(?<![A-Za-z0-9_./-])" + re.escape(h) + rb"(?![A-Za-z0-9_-])") for h in HELPERS}
    for f in root.rglob("*"):
        if f.is_symlink() or not f.is_file() or f.stat().st_size > 400 * 1024 * 1024:
            continue
        data = f.read_bytes()
        for m in PATHS.findall(data):
            paths[m.decode("ascii", "replace")] += 1
        if data[:4] == b"\x7fELF" or data[:2] == b"#!" or f.suffix in (".sh", ".py", ".desktop", ".json", ".xml"):
            for h, rx in word.items():
                if rx.search(data):
                    helpers[h.decode()] += 1
    return paths, helpers


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        paths, helpers = scan(Path(arg))
        print(f"== {arg}")
        by_dir = Counter(re.match(r"/(?:usr/)?[a-z0-9]+(?:/[a-z0-9]+)?", p).group(0) for p in paths if re.match(r"/(?:usr/)?[a-z0-9]+(?:/[a-z0-9]+)?", p))
        print("top dirs:", dict(by_dir.most_common(12)))
        under = sorted(p for p in paths if p.startswith(("/usr/bin/", "/usr/sbin/", "/usr/libexec/", "/bin/", "/sbin/", "/usr/share/applications")))
        print("exec-like paths:", under[:40])
        print("helpers named in files:", dict(helpers.most_common()))
