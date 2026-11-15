#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0
# guests: debian ubuntu fedora
# 07: Muffin 6.4 ends when its clients connect (Cinnamon 6.4 on it: intermittent; 6.8: survives)
set -u
cd ~/appjail && OUT=$(mktemp -d) &&
python3 tests/compositors/probe.py --only muffin --only cinnamon --out "$OUT/r.json" >/dev/null 2>&1
python3 -I - "$OUT/r.json" <<'PY'
import json, sys
bad = 0
for key, r in json.load(open(sys.argv[1]))["compositors"].items():
    if r.get("status") != "ok":
        print(f"  {key}: skipped ({r.get('status')})"); continue
    survived = r.get("survived_clients")
    new = "6.8" in r["version"]
    ok = survived is True if new else (survived is False or key == "cinnamon")  # the shell on Muffin 6.4 is intermittent
    bad += not ok
    print(f"  {key} {r['version']}: survived the clients (wl-copy, wl-paste, grim, wtype)={survived}; {'as expected' if ok else 'UNEXPECTED'} ({'6.8 survives' if new else '6.4 ends (Cinnamon: intermittent)'})")
sys.exit(1 if bad else 0)
PY
