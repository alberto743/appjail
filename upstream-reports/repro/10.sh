#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0
# guests: debian ubuntu fedora
# 10: Wayfire, Cage and Weston do not offer wp_security_context_v1 and list privileged globals on the only socket
set -u
cd ~/appjail && OUT=$(mktemp -d) &&
python3 tests/compositors/probe.py --only wayfire --only cage --only weston --out "$OUT/r.json" >/dev/null 2>&1
python3 -I - "$OUT/r.json" <<'PY'
import json, sys
bad = 0
for key, r in json.load(open(sys.argv[1]))["compositors"].items():
    w = r.get("wayland") or {}
    priv = sorted(n for v in (w.get("full_privileged") or {}).values() for n in v)
    ok = r.get("status") == "ok" and w.get("security_context") is False and bool(priv)
    bad += not ok
    print(f"  {key} {r.get('version')}: security context={w.get('security_context')}; privileged globals on the only socket: {len(priv)} {priv[:6]}; {'REPRODUCED' if ok else 'NOT REPRODUCED'}")
sys.exit(1 if bad else 0)
PY
