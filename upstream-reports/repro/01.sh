#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0
# guests: debian ubuntu fedora
# 01: a client with only a window takes the keyboard focus through gtk_shell1 (Mutter, Muffin, Cinnamon)
set -u
cd ~/appjail && OUT=$(mktemp -d) &&
python3 tests/compositors/focus_steal.py --only mutter,muffin,cinnamon --out "$OUT/r.json" >/dev/null 2>&1
python3 -I - "$OUT/r.json" <<'PY'
import json, sys
bad = 0
for key, r in json.load(open(sys.argv[1]))["compositors"].items():
    if r.get("status") != "ok":
        print(f"  {key} {r.get('version')}: skipped ({r.get('status')})"); continue
    steps = {s["command"]: s for s in r["steps"] if "command" in s}
    control = steps.get("nothing", {}).get("thief_focused")
    stole = [c for c, s in steps.items() if c != "nothing" and s.get("thief_focused")]
    ok = control is False and "present 0" in stole
    bad += not ok
    print(f"  {key} {r['version']}: control kept focus away={control is False}; took the focus with {stole}; {'REPRODUCED' if ok else 'NOT REPRODUCED'}")
sys.exit(1 if bad else 0)
PY
