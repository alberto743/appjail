# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The Console the GUI hands to the commands. It runs on a worker thread and never touches tkinter.

Output and prompts go to a queue the Tk thread drains. A prompt blocks the worker until the Tk thread answers; a cancelled
dialog (or a closing window) answers None, which aborts the command. Confirmations default to No.
"""

import queue

from .. import textsafe
from ..console import Abort, Console


class Request:
    """One prompt: the Tk thread shows it and calls reply()."""

    def __init__(self, kind, prompt, default=False, options=(), review=()):
        self.kind, self.prompt, self.default, self.options, self.review = kind, prompt, default, tuple(options), tuple(review)
        self._answer = queue.Queue(maxsize=1)

    def reply(self, value):
        self._answer.put(value)

    def wait(self):
        return self._answer.get()


class GuiConsole(Console):
    def __init__(self, events):
        self.events = events  # ("out", text) | ("ask", Request)
        self.lines = []  # everything said so far: a confirmation shows it as the review

    def _say(self, text):
        self.lines.append(text)
        self.events.put(("out", text))

    def out(self, line=""):
        self._say(textsafe.clean(line))

    def warn(self, line):
        self._say("WARNING: " + textsafe.clean(line))

    def _request(self, kind, prompt, **kw):
        req = Request(kind, textsafe.clean(prompt), **kw)
        self.events.put(("ask", req))
        answer = req.wait()
        if answer is None:
            raise Abort("cancelled")
        return answer

    def ask(self, prompt):
        return self._request("ask", prompt, review=self.lines[-40:]).strip()

    def confirm(self, prompt, default=False):
        return self._request("confirm", prompt, default=default, review=self.lines[-40:])

    def choose(self, prompt, options):
        return self._request("choose", prompt, options=[textsafe.clean(str(o)) for o in options], review=self.lines[-40:])
