# Upstream reports

Drafts of reports to the compositors and desktop environments whose Wayland sockets and bus services were measured for
appjail (`docs/compositor-assessment/`). **Nothing here has been filed.** Each report waits for your review; then
`SEED.md` says how a session prepares and files it.

> **These drafts are public.** The branch has been on the public `origin` since mid-November 2026, so the
> security-relevant drafts (01, 04, 08), which describe unfixed behaviour in enough detail to reproduce it, can be read
> by anyone. File them first and promptly, through the private channel where a project names one, and say in the
> report that the draft is public. See "Already public" below.

## What is here

| Path | What |
|---|---|
| `reports/NN-*.md` | one report each: a table of facts for the reviewer, the **issue text** to post, the evidence, reviewer notes (not posted) |
| `repro/NN.sh` | the reproduction of report NN; it runs inside the `*-compositors` guest and prints `REPRODUCED` or `NOT REPRODUCED` with the versions it measured |
| `reproduce.sh` | runs the repro scripts in the guests (from the host: `upstream-reports/reproduce.sh [-g debian\|ubuntu\|fedora] [NN ...]`) |
| `SEED.md` | the instructions for the session that files the approved reports |

The tools behind the repro scripts are in `tests/compositors/` (`probe.py`, `rule_a.py`, `clipboard.py`,
`focus_steal.py` with `focus_client.py`, `gtk_bus_name.py`, `drm_fd.py`, `layer_shell.py`, `mutter_dbus.py`,
`cinnamon_dbus.py`) and use only the Python standard library, the compositors and the small clients that the guests
install (`tests/vm/packages-compositors.txt`). Everything runs in the guests; nothing runs on the host.

## The reports

| # | Report | Target | Class | Our severity | Guests | Review | Filed |
|---|---|---|---|---|---|---|---|
| 01 | [gtk_shell1 lets any client take the keyboard focus](reports/01-gtk-shell-focus-steal.md) | Mutter, Muffin | focus-stealing bypass | medium | debian, ubuntu, fedora | pending | no |
| 02 | [GNOME Shell calls the bus name a window gives](reports/02-gnome-shell-calls-client-named-bus-name.md) | GNOME Shell | confused deputy | low | debian, ubuntu, fedora | pending | no |
| 03 | [wp_drm_lease_device_v1 sends a DRM descriptor to every client](reports/03-drm-lease-descriptor-to-every-client.md) | Mutter | sandbox hardening | low | debian, ubuntu, fedora | pending | no |
| 04 | [KWin's restricted socket lists privileged globals](reports/04-kwin-restricted-socket-privileged-globals.md) | KWin, Plasma | security-context hardening, clipboard read (6.3, 6.6) | medium | debian, ubuntu, fedora | pending | no |
| 05 | [Cinnamon 6.8 offers the layer shell to every client](reports/05-cinnamon-layer-shell-to-every-client.md) | Cinnamon, Muffin | draw over the desktop | medium | fedora (control: debian, ubuntu) | pending | no |
| 06 | [xapp_shell_v1 icon may be an absolute path](reports/06-muffin-xapp-shell-icon-path.md) | Muffin | hardening (source only) | low | fedora | pending | no |
| 07 | [Muffin 6.4 ends on wl-copy and wl-paste](reports/07-muffin-crash-on-clipboard-clients.md) | Muffin | crash | low to medium | debian, ubuntu (control: fedora) | pending | no |
| 08 | [Hyprland 0.53.3: restricted socket lists virtual input](reports/08-hyprland-0.53-restricted-socket-virtual-input.md) | Hyprland | restricted socket not restricted | medium | ubuntu (control: debian) | pending | no |
| 09 | [Hyprland 0.53.3 aborts when a window closes](reports/09-hyprland-0.53-abort-on-window-close.md) | Hyprland | crash | low to medium | ubuntu | pending | no |
| 10 | [No security context on Wayfire, Cage, Weston](reports/10-compositors-without-security-context.md) | Wayfire, Cage, Weston | feature request | low | debian, ubuntu, fedora | pending | no |
| 11 | [Session-bus services privileged for any caller](reports/11-session-bus-privileged-services.md) | Cinnamon, Plasma, Mutter | design question | informational | debian, ubuntu, fedora | pending (consider not filing) | no |
| 12 | [security-context-v1: say what must be hidden](reports/12-wayland-protocols-security-context-hide-list.md) | wayland-protocols | protocol text | n/a | debian, ubuntu, fedora | pending | no |

"Our severity" is the opinion of the person who measured, not a CVSS score; the upstream project decides.

## How the evidence is reproduced

```sh
upstream-reports/reproduce.sh            # every report, every guest it lists (the guests must be up: tests/vm/start.sh)
upstream-reports/reproduce.sh 01 02      # some reports
upstream-reports/reproduce.sh -g fedora  # one guest
```

Each script starts the compositors it needs with fresh processes on a private runtime directory and a private bus, runs
the clients, and checks the result: a control (a client that sends nothing, or the version that hides the global) and
the case. `tests/vm/ssh.sh` and `tests/vm/sync.sh` are the only host-side steps.

Last full run, 2026-11-27, all three guests from fresh images (versions in the output of each script; the first,
2026-11-15): every report printed `REPRODUCED`, with these exceptions and notes:

* versions that moved since the first run, with the same findings: KWin and Plasma 6.6.7 (Ubuntu) and 6.8.3 (Fedora;
  it hides the same seven globals as 6.8.2), Cinnamon 6.8.3 (the layer-shell client painted 78.4 % of the screen
  instead of 94.7 %), Muffin 6.8.5 (the source of report 06, same text). Fedora's `muffin` package has no standalone
  compositor to start, so Muffin is measured on Debian and Ubuntu only, as before;
* 07: Muffin 6.4.1 ended in 5 runs of 6 (it survived once on Ubuntu, which failed that run of the script); the
  Cinnamon 6.4 shell ended in 4 of 6 (it survived on Debian and once on Ubuntu), so it is reported as intermittent and
  the script only requires Muffin to end;
* 09: the crash is intermittent; on Ubuntu it ended the compositor on the first try;
* 05, 08: the control (Cinnamon 6.4 not listing the layer shell, Hyprland 0.55 hiding the virtual input) is part of the
  output.

## Review

Edit the table at the top of each report: `Review: approved`, `rejected` or `changes: <what>`. Nothing is filed without
`approved`. The text under "Issue text" is what will be posted; "Reviewer notes" is not posted.

## Not reported, and why

* **A name shared with a compositor's own D-Bus connection** (`org.kde.touchpad` on KWin 6.8's connection). The names
  of one process share its objects; a sandbox that filters names has to know it. appjail confines it. It is not a KDE
  defect.
* **Mutter's `RemoteDesktop` and `ScreenCast` answering any client of the bus**: the portal model depends on it. It is
  in report 11 as a question, not as a bug.
* **KWin 6.8's clipboard read through `wl-paste`**: it used the focus-based fallback, the ordinary path.

## Already public

Pushed to `main` on 2026-11-15: the Wayland assessment pages and results (`docs/compositor-assessment/`), the decision
page on the accepted limits (which names the `gtk_shell1` focus-taking and the DRM descriptor), and the tools
`focus_steal.py` and `focus_client.py`. This branch, with every draft, its reproduction and the tools behind them,
has been on the public `origin` since mid-November 2026. Reports 01, 04 and 08 should be filed promptly for that
reason.

## Rules for the drafts

No personal data (names, e-mail addresses, home paths, host names, session links) in any file here; use `~` and
placeholders. The reporter's identity is the person who files, not this repository. Every claim is a measured one, or
says it was read in the source only. Anything not tried says so under "Reviewer notes".
