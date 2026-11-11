# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Option A of docs/compositor-assessment/ASSESSMENT.md, tried live: for each compositor, which socket the app would get,
which privileged interfaces are left on it, what verdict follows, and whether a real window client works there.

    python3 tests/compositors/rule_a.py --out /tmp/rule-a.json [--only sway,kwin]

Prototype for the decision: the rule is not in src/ yet. Runs in the *-compositors guests only.
"""

import argparse
import contextlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe

from appjail import wayland
from appjail.errors import RunError

# Globals that are privileged in probe.PRIVILEGED but harmless to the user's other apps on their own:
#  - keyboard-shortcuts inhibit: an app may ask to receive the shortcuts while it has focus (VMs, remote desktops use it);
#  - the capture-source managers: they only name a target, a copy manager (still listed) is what captures.
HARMLESS = {"zwp_keyboard_shortcuts_inhibit_manager_v1", "ext_output_image_capture_source_manager_v1",
            "ext_foreign_toplevel_image_capture_source_manager_v1"}
DANGEROUS = {name: kind for name, kind in probe.PRIVILEGED_BY_NAME.items() if name not in HARMLESS}
WINDOW_CLIENTS = (["weston-simple-shm"], ["foot", "-e", "sleep", "30"])


def rule(interfaces):
    """The privileged interfaces of a registry, {kind: [names]}."""
    found = {}
    for iface in interfaces:
        if iface in DANGEROUS:
            found.setdefault(DANGEROUS[iface], []).append(iface)
    return found


def window(session, directory, name):
    """Whether a real window client stays up for 4 s on this socket (timeout's exit status 124 means it was still running)."""
    for argv in WINDOW_CLIENTS:
        if shutil.which(argv[0]):
            out = probe.run(["timeout", "4", *argv], env=probe.tool_env(session, directory, name), timeout=15)
            return {"client": argv[0], "ok": out.returncode == 124, "detail": (out.stderr or "").strip()[-100:]}
    return {"client": None, "ok": False, "detail": "no window client installed"}


def evaluate(key):
    packages, argv_for, extra = probe.COMPOSITORS[key]
    result = {"version": probe.package_version(*packages)}
    if not shutil.which(argv_for(None)[0]):
        result["status"] = "not installed"
        return result
    with probe.Session() as session, open(session.rt / "compositor.log", "w") as logfile:
        before = probe.sockets(session.rt)
        proc = subprocess.Popen(argv_for(session), env=session.env(extra), stdout=logfile, stderr=logfile, start_new_session=True)
        try:
            display = probe.wait_for_display(proc, session.rt, before)
            if display is None:
                result["status"] = "did not start"
                return result
            result["status"] = "ok"
            full = probe.registry(session.rt, display)
            result["security_context"] = probe.SECURITY_CONTEXT in full
            directory, name, chosen = session.rt, display, full
            result["socket"] = "full"
            if result["security_context"]:
                try:
                    with wayland.RestrictedSocket({"XDG_RUNTIME_DIR": str(session.rt), "WAYLAND_DISPLAY": display}, app_id="rule-a") as path:
                        if path is None:
                            result["socket"] = "restricted socket not made"
                        else:
                            directory, name = Path(path).parent, Path(path).name
                            chosen = None
                            for attempt in range(6):
                                with contextlib.suppress(OSError, RunError):
                                    chosen = probe.registry(directory, name)
                                    break
                                probe.time.sleep(0.5)
                            result["socket"] = "restricted" if chosen is not None else "restricted socket refuses connections"
                            if chosen is not None:
                                result["window"] = window(session, directory, name)
                                result["functional"] = {c: v.get("restricted", {}).get("ok") for c, v in
                                                        probe.functional(session, display, (directory, name)).items()}
                except (OSError, RunError) as e:
                    result["socket"] = f"restricted failed: {e}"
                    chosen = None
            else:
                result["window"] = window(session, directory, name)
            if chosen is None:
                result["verdict"] = "unusable"
            else:
                left = rule(chosen)
                result["left"] = left
                result["verdict"] = "refuse" if left else "run"
        except Exception as e:  # noqa: BLE001
            result["status"] = f"error: {type(e).__name__}: {e}"
        finally:
            probe.stop(proc)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)
    keys = [k for k in probe.COMPOSITORS if not args.only or k in args.only.split(",")]
    data = {"distro": probe.distro(), "compositors": {}}
    for key in keys:
        print(f"== {key}", flush=True)
        data["compositors"][key] = evaluate(key)
        print(json.dumps(data["compositors"][key]), flush=True)
    Path(args.out).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
