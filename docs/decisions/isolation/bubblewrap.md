# bubblewrap, not Firejail or sas

*Decision on [isolation](index.md).*

**Context.** appjail needs to start programs in new namespaces, without root, on Debian 13 and Ubuntu 26.04. The
policy (what each jail contains) must be readable, testable and owned by appjail.

**Options.**

- *Firejail*: a mature sandbox with hundreds of maintained profiles. It is a set-uid root program, so a flaw in it is a
  privilege escalation, and its profiles are text it trusts implicitly rather than pinned, declarative grants. Its
  GPL-2.0 licence also rules out reusing its code or profiles in this MPL-2.0 project.
- *sas* (simple-appimage-sandbox): a shell wrapper around bubblewrap for AppImages. Evaluated as a base and rejected:
  it is shell rather than Python, its defaults are permissive (session bus, network, audio, X11 and Wayland sockets,
  shared `/tmp` and `/etc`, the whole of `/dev`), it mounted AppImages with FUSE, and it would be an external dependency
  that moves on its own schedule. Some of its choices were adopted: the set of namespaces, `--die-with-parent`,
  `--new-session`, the GPU device binds.
- *Flatpak*: the mature route when an app is published there, with runtimes, portals and signed repositories. It does
  not run AppImages released only on GitHub, nor pin a user-chosen release with a quarantine.
- *bubblewrap driven directly*: no privileges, no policy of its own, used by Flatpak.

**Decision.** bubblewrap, driven by argument lists that appjail builds in Python (`jail.py`, `runtimejail.py`). Ideas
from Firejail were taken and written anew: its categories of sensitive files became the checklist for the paths that
can never be granted, and its handling of the environment led to appjail clearing it entirely.

**Consequences.** appjail depends on bubblewrap 0.10 or later and on unprivileged user namespaces being allowed.
Everything bubblewrap does not offer (Landlock, the D-Bus filter, the audio graph) is a separate program appjail starts.
Flatpak remains the better choice for apps it carries; appjail does not compete with it.
