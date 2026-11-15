#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0
# guests: debian ubuntu fedora
# 12: compositors that offer wp_security_context_v1 differ in what their restricted socket hides
set -u
cd ~/appjail && OUT=$(mktemp -d) &&
python3 tests/compositors/rule_a.py --out "$OUT/r.json" >/dev/null 2>&1
python3 -I - "$OUT/r.json" <<'PY'
import json, sys
hides, leaks = [], []
for key, r in json.load(open(sys.argv[1]))["compositors"].items():
    if r.get("socket") != "restricted":
        continue
    left = sorted(n for v in (r.get("left") or {}).values() for n in v)
    (leaks if left else hides).append(key)
    print(f"  {key} {r.get('version')}: privileged globals left on the restricted socket: {len(left)}")
ok = bool(hides) and bool(leaks)
print(f"  hide everything: {hides}; leave some: {leaks}")
print("  REPRODUCED" if ok else "  NOT REPRODUCED")
sys.exit(0 if ok else 1)
PY
