# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Open an issue when a supported system has a newer release (run by check-platforms.yml, monthly).

Compares what the project targets (the guest images of tests/vm/guest.sh and the runner label of the workflows) with
endoflife.date (https://endoflife.date/docs/api/v1/): the current Debian stable, the newest Ubuntu LTS and the newest
Fedora. It only reports: moving to a new release is a decision (support matrix, CI, docs). The API answer is parsed as
JSON and never executed; text that reaches an issue is reduced to a safe alphabet. Stdlib only; `gh` comes from the runner.
"""

import datetime
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

API = "https://endoflife.date/api/v1/products/{}/"
MAX_BYTES = 5 * 1024 * 1024
SAFE = re.compile(r"[^A-Za-z0-9 .'()-]")
LABEL = "platforms"


def key(v):
    return tuple(int(x) for x in v.split("."))


def clean(text):
    return SAFE.sub("", str(text))[:80]


def released(releases, today):
    return [r for r in releases if r.get("releaseDate") and r["releaseDate"] <= today]


def newest(releases):
    return max(releases, key=lambda r: key(r["name"]), default=None)


def current_debian(releases, today):
    """Debian stable: the newest release that is not end of life nor past its active support."""
    return newest([r for r in released(releases, today) if not r.get("isEol") and not r.get("isEoas")])


def current_ubuntu_lts(releases, today):
    return newest([r for r in released(releases, today) if r.get("isLts") and not r.get("isEol")])


def current_fedora(releases, today):
    return newest([r for r in released(releases, today) if not r.get("isEol")])


def targets(guest_sh, workflows):
    """What the project uses: {'debian': '13', 'ubuntu': '26.04', 'fedora': '45'}; a missing one is left out."""
    out = {}
    m = re.search(r"debian-(\d+)-genericcloud", guest_sh)
    if m:
        out["debian"] = m.group(1)
    labels = [m2.group(1) for text in workflows for m2 in re.finditer(r"runs-on:\s*ubuntu-(\d+\.\d+)", text)]
    if labels:  # the runner label is what moves; after the switch to ubuntu-latest there is none
        out["ubuntu"] = max(labels, key=key)
    m = re.search(r"/fedora/linux/releases/(\d+)/", guest_sh)
    if m:
        out["fedora"] = m.group(1)
    return out


def findings(target, latest):
    """[(title, body)] for each system whose current release is newer than the target."""
    out = []
    for product, label in (("debian", "Debian"), ("ubuntu", "Ubuntu LTS"), ("fedora", "Fedora")):
        rel, have = latest.get(product), target.get(product)
        if rel is None or have is None or key(rel["name"]) <= key(have):
            continue
        name = clean(rel["name"])
        title = f"platforms: {label} {name} is out (the project targets {clean(have)})"
        text = (f"endoflife.date lists {label} {name} (released {clean(rel.get('releaseDate'))}); "
                f"the project targets {clean(have)}.\n\n"
                "Moving is a decision, not automatic. If you take it: the guest image in `tests/vm/guest.sh`, the runner "
                "label and the supported systems in `docs/`, `README.md`, `SECURITY.md` and `CLAUDE.md`, then the suite "
                "on every guest.\n"
                "Close this issue to decline; it is not opened again for the same release.")
        out.append((title, text))
    return out


def fetch(product):
    req = urllib.request.Request(API.format(product), headers={"User-Agent": "appjail-check-platforms"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise SystemExit(f"{product}: answer larger than {MAX_BYTES} bytes")
    return json.loads(raw)["result"]["releases"]


def gh(*cmd):
    return subprocess.run(("gh",) + cmd, check=True, text=True, capture_output=True).stdout


def main():
    today = datetime.date.today().isoformat()
    root = Path(__file__).resolve().parents[2]
    workflows = [p.read_text() for p in (root / ".github/workflows").glob("*.yml")]
    target = targets((root / "tests/vm/guest.sh").read_text(), workflows)
    latest = {"debian": current_debian(fetch("debian"), today), "ubuntu": current_ubuntu_lts(fetch("ubuntu"), today),
              "fedora": current_fedora(fetch("fedora"), today)}
    print("targets:", target)
    print("current:", {k: v and v["name"] for k, v in latest.items()})
    found = findings(target, latest)
    if not found:
        print("up to date")
        return
    known = {i["title"] for i in json.loads(gh("issue", "list", "--state", "all", "--limit", "200", "--json", "title"))}
    gh("label", "create", LABEL, "--description", "A supported system has a new release", "--force")
    for title, text in found:
        if title in known:
            print(f"already reported: {title}")
            continue
        gh("issue", "create", "--label", LABEL, "--title", title, "--body", text)
        print(f"opened: {title}")


if __name__ == "__main__":
    sys.exit(main())
