# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Run a CLI command off the Tk thread, either in-process (commands that prompt) or as a detached child (run, open)."""

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from .. import cli, textsafe
from .console import GuiConsole


def run_command(argv, events):
    """Start `appjail ARGV` on a thread. Puts ("out", ...) / ("ask", ...) on events, then ("done", status)."""
    def work():
        status = 1
        try:
            status = cli.main(argv, console=GuiConsole(events))
        except SystemExit:  # argparse rejected the arguments (its message went to stderr)
            events.put(("out", "error: invalid arguments"))
            status = 2
        except Exception as e:  # noqa: BLE001  (a bug in a command must not leave the window waiting; the cause is shown)
            events.put(("out", textsafe.clean(f"error: {type(e).__name__}: {e}")))
        events.put(("done", status))

    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t


def spawn_detached(argv, events):
    """Start `python -m appjail ARGV` in its own session, so closing the GUI does not end the app. Streams its output."""
    env = dict(os.environ)
    src = str(Path(cli.__file__).resolve().parent.parent)
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    proc = subprocess.Popen([sys.executable, "-m", "appjail", *argv], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, text=True, errors="replace", env=env, start_new_session=True)

    def pump():
        for line in proc.stdout:
            events.put(("out", textsafe.clean(line.rstrip("\n"))))
        events.put(("done", proc.wait()))

    threading.Thread(target=pump, daemon=True).start()
    return proc


def new_events():
    return queue.Queue()
