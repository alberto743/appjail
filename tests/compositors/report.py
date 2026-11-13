# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The tables of docs/compositor-assessment/ASSESSMENT.md, generated from the saved results of the tools in this directory.

    python3 tests/compositors/report.py            # print every table
    python3 tests/compositors/report.py --write    # rewrite the tables in ASSESSMENT.md
    python3 tests/compositors/report.py --check    # exit 1 if ASSESSMENT.md differs from the results (tests/test_assessment.py)

In ASSESSMENT.md a table sits between `<!-- generated:NAME -->` and `<!-- /generated -->`; NAME is one of SECTIONS. Nothing is
measured here: every cell is read from the results-*.json (probe.py), rule-a-*.json, clipboard-*.json, mutter-dbus-*.json,
cinnamon-dbus-*.json and shared-connection-*.json files next to it.
"""

import contextlib
import json
import re
import sys
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[2] / "docs" / "compositor-assessment"
DOCUMENT = "ASSESSMENT.md"
CAPABILITIES = ("capture", "clipboard", "type")
BLOCK = re.compile(r"(<!-- generated:(\w+) -->\n)(.*?)(<!-- /generated -->)", re.DOTALL)


def load(directory, prefix):
    """[(distribution label, compositors)] from the `prefix`-*.json files of a directory, in file-name order."""
    out = []
    for path in sorted(Path(directory).glob(f"{prefix}-*.json")):
        data = json.loads(path.read_text())
        d = data["distro"]
        out.append((f"{d['id']} {d['version']}", data["compositors"]))
    return out


def yes(flag):
    return "yes" if flag else "no"


def version(entry):
    text = (entry or {}).get("version") or "-"
    return text.split(" ", 1)[-1]


def table(head, rows):
    lines = [head, ["---"] * len(head), *rows]
    return "\n".join("| " + " | ".join(r) + " |" for r in lines)


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
    rows = []
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
    return table(head, rows)


def rule_table(results):
    """The rule of `appjail run` applied live: the socket the app gets, what is left on it, and the verdict."""
    names = sorted({k for _, comps in results for k in comps})
    head = ["Compositor", "Distribution", "Version", "Socket the app gets", "Privileged interfaces left on it", "Window client", "Verdict"]
    rows = []
    for name in names:
        for label, comps in results:
            entry = comps.get(name)
            if not entry or entry["status"] != "ok":
                rows.append([name, label, version(entry), "-", "-", "-", (entry or {}).get("status", "not run")])
                continue
            left = "; ".join(f"{kind}: {', '.join(found)}" for kind, found in sorted(entry.get("left", {}).items())) or "nothing"
            window = entry.get("window")
            rows.append([name, label, version(entry), entry.get("socket", "-"), left,
                         "-" if not window else ("works" if window["ok"] else "failed"), entry.get("verdict", "-")])
    return table(head, rows)


def clipboard_table(results):
    """Copy and paste with keyboard focus between a window outside and a window on the socket the app gets."""
    names = sorted({k for _, comps in results for k in comps})
    head = ["Compositor", "Distribution", "Version", "Socket the app gets", "Outside → app", "App → outside"]
    rows = []
    for name in names:
        for label, comps in results:
            entry = comps.get(name)
            if not entry or entry["status"] != "ok":
                rows.append([name, label, version(entry), "-", "-", (entry or {}).get("status", "not run")])
                continue
            rows.append([name, label, version(entry), entry.get("app_socket", "-"), entry.get("inbound", "-"), entry.get("outbound", "-")])
    return table(head, rows)


def call_outcome(call):
    """`allowed`, `refused` or `not called`. An Eval that answers (false, ...) refused to run the script (GNOME Shell outside
    its unsafe mode), although the call itself went through."""
    if call["ok"] is None:
        return "not called"
    if call["ok"] and call["member"].endswith(".Eval"):
        with contextlib.suppress(ValueError, KeyError, IndexError, TypeError):
            if json.loads(call["answer"])["data"][0] is False:
                return "refused"
    return "allowed" if call["ok"] else "refused"


def dbus_table(results):
    """Per compositor with D-Bus names: each call made as an ordinary client and whether the compositor allowed it."""
    seen = {}
    for label, comps in results:
        for name, entry in comps.items():
            for call in (entry.get("dbus") or {}).get("calls", []):
                seen.setdefault((name, call["member"]), {})[label] = call_outcome(call)
    labels = [label for label, _ in results]
    rows = []
    for (name, member), outcome in sorted(seen.items()):
        short = ".".join(member.split(".")[-2:])
        rows.append([name, f"`{short}`", *[outcome.get(label, "-") for label in labels]])
    return table(["Compositor", "Call, as an ordinary client", *labels], rows)


def policy_table(results):
    """Privileged-looking D-Bus names and what appjail's name policy did with them when the survey ran."""
    rows = []
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
    return table(["Compositor", "Bus names on a connection with privileged-looking interfaces", "appjail policy when surveyed"], rows)


def mutter_dbus_table(results):
    """A complete keystroke into another client's window and a complete screen capture, through Mutter's own D-Bus API as an
    ordinary client of the bus (mutter_dbus.py)."""
    names = sorted({k for _, comps in results for k in comps})
    head = ["Compositor", "Distribution", "Version", "RemoteDesktop: keys typed into another client's window",
            "ScreenCast: a whole frame of the screen"]
    rows = []
    for name in names:
        for label, comps in results:
            entry = comps.get(name)
            if not entry or entry["status"] != "ok":
                rows.append([name, label, version(entry), "-", (entry or {}).get("status", "not run")])
                continue
            typed, shot = entry["type"], entry["capture"]
            rows.append([name, label, version(entry),
                         f"yes (`{typed['received']}`)" if typed["ok"] else f"no ({typed.get('error') or 'nothing received'})",
                         f"yes ({shot['bytes'] // 3} pixels, {shot['colours']} colours)" if shot["ok"]
                         else f"no ({shot.get('error') or shot.get('gst_error') or 'no frame'})"])
    return table(head, rows)


def cinnamon_dbus_table(results):
    """What an ordinary client of the bus did through Cinnamon's own names (cinnamon_dbus.py)."""
    head = ["Distribution", "Version", "Eval: a command run as the user", "Eval: keys typed into another client's window",
            "Screenshot: the whole screen", "SelectArea: Cinnamon still running afterwards"]
    rows = []
    for label, comps in results:
        entry = comps.get("cinnamon")
        if not entry or entry["status"] != "ok":
            rows.append([label, version(entry), (entry or {}).get("status", "not run"), "-", "-", "-"])
            continue
        typed, shot = entry["type"], entry["capture"]
        rows.append([label, version(entry), yes(entry["command"]["ok"]),
                     f"yes (`{typed['received']}`)" if typed["ok"] else "no",
                     f"yes ({shot['width']}x{shot['height']}, the other client's window in it)" if shot["ok"] else "no",
                     yes(entry["select_area"]["survived"])])
    return table(head, rows)


def shared_connection_table(results):
    """Names appjail's policy allows, owned by the same connection as a refused privileged name: whether the privileged call,
    sent to the allowed name through xdg-dbus-proxy started as appjail starts it, reached the compositor (shared_connection.py)."""
    labels = [label for label, _ in results]
    seen = {}
    for label, comps in results:
        for comp, entry in comps.items():
            for name, tried in (entry.get("tries") or {}).items():
                seen.setdefault((comp, name, tried["call"]), {})[label] = "yes" if tried["reached"] else "no"
    rows = [[comp, f"`{name}`", f"`{'.'.join(call.split('.')[-2:])}`", *[got.get(label, "-") for label in labels]]
            for (comp, name, call), got in sorted(seen.items())]
    return table(["Compositor", "Granted name (allowed)", "Call sent to it", *[f"reached, {label}" for label in labels]], rows)


def sections(directory=DIRECTORY):
    """{name: markdown table} for every table that can be generated from the files of this directory."""
    survey = load(directory, "results")
    return {"wayland": wayland_table(survey), "rule": rule_table(load(directory, "rule-a")),
            "clipboard": clipboard_table(load(directory, "clipboard")), "dbus": dbus_table(survey), "policy": policy_table(survey),
            "mutter_dbus": mutter_dbus_table(load(directory, "mutter-dbus")),
            "cinnamon_dbus": cinnamon_dbus_table(load(directory, "cinnamon-dbus")),
            "shared_connection": shared_connection_table(load(directory, "shared-connection"))}


def splice(document, tables):
    """The document with each generated block replaced by its table; a block with an unknown name is an error."""
    def fill(m):
        if m.group(2) not in tables:
            raise ValueError(f"unknown generated block: {m.group(2)}")
        return m.group(1) + tables[m.group(2)] + "\n" + m.group(4)
    return BLOCK.sub(fill, document)


def main(argv):
    path = DIRECTORY / DOCUMENT
    if "--check" in argv or "--write" in argv:
        old = path.read_text()
        new = splice(old, sections())
        if "--write" in argv:
            path.write_text(new)
            return 0
        if new != old:
            print(f"{DOCUMENT} differs from the saved results: run report.py --write", file=sys.stderr)
            return 1
        return 0
    print("\n\n".join(f"### {name}\n\n{text}" for name, text in sections().items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
