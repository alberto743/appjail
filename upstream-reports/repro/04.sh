#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0
# guests: debian ubuntu fedora
# 04: KWin's restricted socket still lists privileged globals (6.3, 6.6: data-control and a clipboard read; 6.8: the layer shell and more)
set -u
cd ~/appjail && OUT=$(mktemp -d) &&
python3 tests/compositors/rule_a.py --only kwin --out "$OUT/r.json" >/dev/null 2>&1
python3 -I - "$OUT/r.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))["compositors"]["kwin"]
left = r.get("left") or {}
names = sorted(n for v in left.values() for n in v)
clip = bool(left.get("clipboard"))
print(f"  {r['version']}: socket={r.get('socket')}; privileged globals left on the restricted socket: {names}")
print(f"  another client's clipboard read through it: {(r.get('functional') or {}).get('clipboard')} (data-control listed: {clip})")
ok = r.get("socket") == "restricted" and "zwlr_layer_shell_v1" in names
print("  REPRODUCED" if ok else "  NOT REPRODUCED")
sys.exit(0 if ok else 1)
PY
