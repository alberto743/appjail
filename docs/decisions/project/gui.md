# A window over the command line

*Decision on [the project](index.md).*

**Context.** Some users prefer a window, and some tasks (choosing permissions, file types) are easier with one. appjail
has no dependencies beyond Python's standard library.

**Decision.** `appjail-gui` is a tkinter window shipped in the same package. tkinter is in the standard library, but
Debian and Ubuntu package it separately (`python3-tk`), so the window is optional and loaded only when used; the command
line never needs it. It reimplements no command: each action builds a command line, runs the same CLI on a worker
thread, and shows its prompts as dialogs that default to No. It never adds `--yes`. The only direct reads are for lists
(installed apps from their manifests, search results from the catalogs), so rows can be selected; installing still goes
through `add`.

**Rejected.** A toolkit from PyPI (Qt or GTK bindings), which would break the standard-library rule.

**Consequences.** One parser, one set of checks and the same reviews for both interfaces. Long downloads show no
progress, since they run in a jail with no incremental output.

**Revisit when** a command needs progress or cancellation that a worker thread cannot give.
