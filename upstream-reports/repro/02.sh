#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0
# guests: debian ubuntu fedora
# 02: GNOME Shell calls a D-Bus name that a window gives in gtk_surface1.set_dbus_properties
set -u
cd ~/appjail && OUT=$(mktemp -d) &&
python3 tests/compositors/gtk_bus_name.py --out "$OUT/r.json" >/dev/null 2>&1
python3 -I - "$OUT/r.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
c, w = r["control"], r["with_properties"]
ok = c.get("status") == "ok" and w.get("status") == "ok" and not c["called"] and w["called"]
print(f"  {w.get('version')}: control calls={len(c.get('calls_to_the_name', []))}; with set_dbus_properties calls={len(w.get('calls_to_the_name', []))}")
for line in w.get("calls_to_the_name", []):
    print("   ", line.split("path=")[-1])
print("  REPRODUCED" if ok else "  NOT REPRODUCED")
sys.exit(0 if ok else 1)
PY
