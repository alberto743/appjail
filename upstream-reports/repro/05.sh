#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0
# guests: fedora debian ubuntu
# 05: Cinnamon 6.8 offers zwlr_layer_shell_v1 to every client: swaybg paints the desktop (Cinnamon 6.4 does not list it: the control)
set -u
cd ~/appjail && OUT=$(mktemp -d) &&
python3 tests/compositors/layer_shell.py --out "$OUT/r.json" >/dev/null 2>&1
python3 -I - "$OUT/r.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))["cinnamon"]
print(f"  {r.get('version')}: layer shell listed={r.get('layer_shell_listed')}; share of the screen painted by the client={r.get('share_with_client')} (control {r.get('control_share')})")
new = "6.8" in r.get("version", "")
ok = r.get("draws_over_the_desktop") if new else r.get("layer_shell_listed") is False
print("  REPRODUCED" if ok else "  NOT REPRODUCED", "" if new else "(6.4: the layer shell is not offered, as expected)")
sys.exit(0 if ok else 1)
PY
