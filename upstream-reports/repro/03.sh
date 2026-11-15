#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0
# guests: debian ubuntu fedora
# 03: wp_drm_lease_device_v1 sends a DRM file descriptor to a client with only a window (Mutter, GNOME Shell)
set -u
cd ~/appjail && OUT=$(mktemp -d) &&
python3 tests/compositors/drm_fd.py --only mutter,gnome-shell --out "$OUT/r.json" >/dev/null 2>&1
python3 -I - "$OUT/r.json" <<'PY'
import json, sys
bad = 0
for key, r in json.load(open(sys.argv[1]))["compositors"].items():
    d = (r.get("full") or {}).get("descriptors") or []
    ok = any(x["node"].startswith("/dev/dri/") for x in d)
    bad += not ok
    print(f"  {key} {r.get('version')}: descriptors received on the compositor's socket: {[x['node'] for x in d]}; {'REPRODUCED' if ok else 'NOT REPRODUCED'}")
sys.exit(1 if bad else 0)
PY
