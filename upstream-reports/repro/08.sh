#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0
# guests: ubuntu debian
# 08: Hyprland 0.53.3's restricted socket lists virtual input and wtype types through it (0.55.2 hides them)
set -u
cd ~/appjail && OUT=$(mktemp -d) &&
python3 tests/compositors/rule_a.py --only hyprland --out "$OUT/r.json" >/dev/null 2>&1
python3 -I - "$OUT/r.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))["compositors"]["hyprland"]
left = sorted(n for v in (r.get("left") or {}).values() for n in v)
typed = (r.get("functional") or {}).get("type")
new = r["version"].split()[-1].startswith("0.55")
print(f"  {r['version']}: socket={r.get('socket')}; privileged globals left={left}; typed through the restricted socket={typed}")
ok = (not left and not typed) if new else ("zwp_virtual_keyboard_manager_v1" in left and typed is True)
print("  REPRODUCED" if ok else "  NOT REPRODUCED", "(0.55 hides them: the control)" if new else "")
sys.exit(0 if ok else 1)
PY
