# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Markdown tables from the results of probe.py, one results file per distribution.

    python3 tests/compositors/report.py docs/compositor-assessment/results-*.json

Nothing is measured here: every cell is read from the files.
"""

import json
import sys
from pathlib import Path

CAPABILITIES = ("capture", "clipboard", "type")
LABELS = {"capture": "capture", "clipboard": "clipboard", "type": "typing"}


def load(paths):
    """[(distribution label, results)] in the order given."""
    out = []
    for path in paths:
        data = json.loads(Path(path).read_text())
        d = data["distro"]
        out.append((f"{d['id']} {d['version']}", data["compositors"]))
    return out


def yes(flag):
    return "yes" if flag else "no"


def version(entry):
    text = (entry or {}).get("version") or "-"
    return text.split(" ", 1)[-1]


def functional_cell(wayland, label):
    """What a client could do on this socket, as `capture/clipboard/typing`, or `-` when there is no such socket."""
    f = wayland.get("functional") or {}
    if not all(label in f.get(c, {}) for c in CAPABILITIES):
        return "-"
    return "/".join(yes(f[c][label]["ok"]) for c in CAPABILITIES)


def wayland_table(results):
    """One row per compositor and distribution."""
    names = sorted({k for _, comps in results for k in comps})
    head = ["Compositor", "Distribution", "Version", "Security context", "Privileged interfaces on the full socket",
            "Full socket: capture / clipboard / typing", "Restricted socket: capture / clipboard / typing", "Note"]
    rows = [head, ["---"] * len(head)]
    for name in names:
        for label, comps in results:
            entry = comps.get(name)
            if not entry or entry["status"] != "ok":
                rows.append([name, label, version(entry), "-", "-", "-", "-", (entry or {}).get("status", "not surveyed")])
                continue
            w = entry["wayland"]
            note = w.get("restricted_error", "")
            rows.append([name, label, version(entry), yes(w["security_context"]),
                         str(sum(len(v) for v in w["full_privileged"].values())),
                         functional_cell(w, "full"), functional_cell(w, "restricted"), note[:70]])
    return "\n".join("| " + " | ".join(r) + " |" for r in rows)


def dbus_table(results):
    """Per compositor with D-Bus names: each call made as an ordinary client and whether the compositor allowed it."""
    seen = {}
    for label, comps in results:
        for name, entry in comps.items():
            for call in (entry.get("dbus") or {}).get("calls", []):
                seen.setdefault((name, call["member"]), {})[label] = call["ok"]
    labels = [label for label, _ in results]
    rows = [["Compositor", "Call, as an ordinary client", *labels], ["---"] * (2 + len(labels))]
    for (name, member), outcome in sorted(seen.items()):
        short = ".".join(member.split(".")[-2:])
        rows.append([name, f"`{short}`", *["allowed" if outcome.get(label) else ("refused" if label in outcome else "-") for label in labels]])
    return "\n".join("| " + " | ".join(r) + " |" for r in rows)


def policy_table(results):
    """Privileged-looking D-Bus names and what appjail's own name policy does with them."""
    rows = [["Compositor", "Bus names on a connection with privileged-looking interfaces", "appjail policy"], ["---"] * 3]
    done = set()
    for _label, comps in results:
        for name, entry in comps.items():
            for conn in (entry.get("dbus") or {}).get("connections", []):
                if not conn["privileged_looking"]:
                    continue
                key = (name, tuple(conn["names"]))
                if key in done:
                    continue
                done.add(key)
                policy = entry["dbus"]["names"]
                allowed = [n for n in conn["names"] if policy[n]["appjail_policy_allows"]]
                refused = [n for n in conn["names"] if not policy[n]["appjail_policy_allows"]]
                rows.append([name, ", ".join(f"`{n}`" for n in conn["names"]),
                             f"allows {len(allowed)}, refuses {len(refused)}" + (f" (allows: {', '.join(allowed)})" if allowed else "")])
    return "\n".join("| " + " | ".join(r) + " |" for r in rows)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    results = load(argv)
    print("### Wayland\n\n" + wayland_table(results) + "\n\n### D-Bus calls\n\n" + dbus_table(results)
          + "\n\n### appjail's D-Bus name policy\n\n" + policy_table(results))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
