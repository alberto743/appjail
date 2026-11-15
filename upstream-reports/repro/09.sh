#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0
# guests: ubuntu
# 09: Hyprland 0.53.3 aborts when a window closes (flaky: it depends on what is left on the screen; up to 3 tries)
set -u
cd ~/appjail && OUT=$(mktemp -d) && n=0
while [ $n -lt 3 ]; do
  n=$((n+1))
  python3 tests/compositors/clipboard.py --only hyprland --out "$OUT/r$n.json" >/dev/null 2>&1
  if grep -q "crashed" "$OUT/r$n.json"; then
    echo "  try $n: $(grep -h -o 'untestable ([^)]*crashed[^)]*)' "$OUT/r$n.json" | head -1)"
    echo "  REPRODUCED"; exit 0
  fi
  echo "  try $n: the compositor survived"
done
echo "  NOT REPRODUCED in 3 tries"; exit 1
