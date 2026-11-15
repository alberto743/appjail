#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0
# guests: debian ubuntu fedora
# 11: session-bus services that run code, read the clipboard or capture the screen for any client of the bus
set -u
cd ~/appjail && OUT=$(mktemp -d) &&
python3 tests/compositors/probe.py --only cinnamon --only plasmashell --only mutter --out "$OUT/r.json" >/dev/null 2>&1
python3 -I - "$OUT/r.json" <<'PY'
import json, sys
WANT = ("org.Cinnamon.Eval", "org.kde.PlasmaShell.evaluateScript", "org.kde.klipper.klipper.getClipboardContents",
        "org.gnome.Mutter.ScreenCast.CreateSession", "org.gnome.Mutter.RemoteDesktop.CreateSession")
seen = {}
for key, r in json.load(open(sys.argv[1]))["compositors"].items():
    for call in (r.get("dbus") or {}).get("calls", []):
        if call["member"] in WANT:
            seen[call["member"]] = call["ok"]
            print(f"  {key} {r.get('version')}: {call['member']} answered an ordinary client of the bus: {call['ok']}")
ok = bool(seen) and all(seen.values())
print("  REPRODUCED" if ok else "  NOT REPRODUCED")
sys.exit(0 if ok else 1)
PY
