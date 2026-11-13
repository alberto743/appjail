# Assessing a Wayland compositor

How appjail's compositor assessment is made, so that a compositor, a new version of one, or a whole desktop can be added
the same way. The results and the decisions taken from them are in
[compositor-assessment/ASSESSMENT.md](../compositor-assessment/ASSESSMENT.md); the rules they feed are `wayland.PRIVILEGED`
and `wayland.ALLOWED` (`src/appjail/wayland.py`) and `grants.DBUS_BLOCKED` (`src/appjail/grants.py`).

## The question

Can an app with default permissions capture the screen, read or inject input, read another app's clipboard, take over the
desktop or run commands outside its jail, through what the desktop offers it? A desktop offers two things: the Wayland
socket the app gets, and the names on the session bus a user may grant. Both are measured. Advertised is not usable:
every capability is tried with a real client, and every claim in ASSESSMENT.md points at a saved result.

## Where

Only in the `*-compositors` guests (`GUEST=debian-compositors`, `GUEST=ubuntu-compositors`; packages in
`tests/vm/packages-compositors.txt`), never on the host. Both distributions, identical code, each compositor in a private
runtime directory and on a private session bus (`probe.Session`). A compositor is measured in the version its distribution
packages; one that neither packages is not measured, and the rule decides it from its registry at run time.

## The tools (`tests/compositors/`)

| Tool | Measures | Results file |
|---|---|---|
| `probe.py` | the registry of the compositor's socket and of the restricted one (with `wayland-info` as a second reader); capture (`grim`), another client's clipboard (`wl-copy`, `wl-paste`), typing (`wtype`) on each; the bus names the compositor owns, their interfaces, side-effect-free calls as an ordinary client (`CALLS`) | `results-*.json` |
| `rule_a.py` | appjail's rule: the socket the app gets, the privileged globals left on it, a real window client there, the verdict | `rule-a-*.json` |
| `clipboard.py` | ordinary copy and paste with keyboard focus, both directions, between a window outside and one on the app's socket | `clipboard-*.json` |
| `mutter_dbus.py`, `cinnamon_dbus.py` | a desktop's privileged D-Bus API used end to end as an ordinary client: keys typed into another client's window, a whole screen captured with that window in it, a command run | `mutter-dbus-*.json`, `cinnamon-dbus-*.json` |
| `shared_connection.py` | for every name appjail allows that is owned by the connection of a refused one: whether the privileged call, sent to the allowed name through xdg-dbus-proxy with `--talk`, reaches the compositor, and what appjail does with that grant (refused at launch, or confined: the privileged call by name and by unique name, the service's own call) | `shared-connection-*.json` |
| `report.py` | the tables of ASSESSMENT.md from the results (`--write`; `tests/test_assessment.py` checks them) | |

## Adding a compositor

1. **Package.** Add it to `tests/vm/packages-compositors.txt` with a comment (what it is, how it starts), plus whatever it
   needs to start (Muffin needs `cinnamon-settings-daemon` for its GSettings schemas). Provision both guests.
2. **Start it headless.** Add an entry to `probe.COMPOSITORS`: packages, command line, environment. Use its headless
   backend if it has one (`--headless`, `--virtual`, `WLR_BACKENDS=headless`, `AQ_BACKENDS=headless`). If it has none, run
   it nested as a window of a private Xvfb (`probe.XVFB`, as Muffin and Cinnamon do); weston is also measured as a window of
   a headless sway. A shell that is a plugin of a compositor (GNOME Shell on Mutter, Cinnamon on Muffin) is its own entry; so is a shell that
   is a client of one (plasmashell beside KWin, with the activity manager it needs; `probe.SETTLE` gives it time to load).
3. **Survey.** `probe.py --only NAME` on both guests. Read `full`, `restricted`, `functional` and `dbus`.
4. **Classify every global it lists** that is in neither `wayland.PRIVILEGED` nor `wayland.ALLOWED`: read the protocol's XML
   and decide whether it acts only on the app's own windows, on input while the app has focus, or on its own buffers
   (allowed), or on other apps, the screen, input in general or the desktop (privileged). An unknown global refuses the app,
   so leaving one unclassified is safe but refuses the compositor.
5. **Read its D-Bus.** For every name it owns: the interfaces (`busctl introspect`), and what appjail's policy does with it
   (`appjail_policy_*`). Add side-effect-free calls for privileged-looking interfaces to `probe.CALLS` (a getter, a session
   created and not started, an `Eval` of `1+1`). A refused call means the compositor checks the caller; an allowed one means
   only the bus stands in the way.
6. **Go end to end where a call is allowed.** If a privileged API answers an ordinary client, write the complete use as a
   tool (like `mutter_dbus.py`, `cinnamon_dbus.py`): a GTK 4 window of another client with a red background that logs the
   keys it receives (`mutter_dbus.py window`) is the victim; a capture must hold its red pixels and be the size of the whole
   screen; a command must leave a file. Run it three times per distribution.
7. **Check the connection, not just the name.** Run `shared_connection.py` with the compositor added to `PRIVILEGED_CALL`
   (its refused name and its privileged call). With `--talk`, a name appjail allows on the same connection reaches
   everything that connection serves; every row's `appjail` outcome must be "refused at launch" or "confined" with the
   privileged call blocked. A name the compositor owns that apps need (a service of its own) goes in `dbusproxy.CONFINED`
   with its specified interfaces and path, and in `SERVICE_CALL` with a harmless call of its own.
8. **Rule and clipboard.** `rule_a.py --only NAME` and `clipboard.py --only NAME`. `clipboard.py` needs a keyboard on the
   headless seat: a persistent `wtype` where the virtual-keyboard protocol exists, Mutter's RemoteDesktop for Mutter and GNOME
   Shell, a nested run otherwise.
9. **Save.** Merge the new compositor's entry into each existing results file (inside the guest, so the host runs nothing)
   rather than rerunning everything: the survey's `appjail_policy_*` fields record the policy as it was when it ran. Copy
   the files back, run `report.py --write` in a guest, add the new `generated` blocks to ASSESSMENT.md and to
   `tests/test_assessment.py`.
10. **Decide and document.** Change `wayland.PRIVILEGED` or `ALLOWED`, `grants.DBUS_BLOCKED` and `tests/test_dbus.py` as the
    results require; update ASSESSMENT.md (what the table shows, decision D, the limits), the decision pages under
    `docs/decisions/desktop/` (why), `docs/understand/desktop/` (the refused names), and the compositor table in
    `docs/guide/compositors.md`; regenerate `docs/reference/policy.md`; run the full suite on both guests.

## Lessons from the measurements

* **Read D-Bus first.** A client of the functional checks can crash the compositor (Muffin and Cinnamon die serving
  `wl-copy` and `wl-paste`), and its bus names go with it. probe.py reads the bus before running clients and records
  `survived_clients`.
* **A call can end the compositor.** `org.gnome.Shell.Screenshot.SelectArea` ends Cinnamon nested in Xvfb; probe.py skips it
  there (`probe.ENDS_COMPOSITOR`) and `cinnamon_dbus.py` makes it last, recording whether the shell survived.
* **When a client never gets focus, check that the compositor is still there.** Hyprland 0.53.3 aborts when a window closes;
  that looked like a focus problem until `clipboard.py` asked the registry again.
* **KWin reads each positional argument as a whole command line** (split like a shell would), and a child it starts
  inherits its environment, `QT_QPA_PLATFORM=offscreen` included: start Plasma's shell beside KWin, not through it.
* **Shells take their bus names after the socket appears.** Wait a few seconds after `wait_for_display` before listing them.
* **GNOME Shell starts in its overview**, which takes the first click and keys: press Escape, wait, and retry the typing.
  **Mutter focuses a new window at the first key after a click** and does not deliver that key: send a Shift first.
* **Read the answer, not only the reply.** GNOME Shell's `Eval` returns `(false, "")` outside its unsafe mode: the call went
  through, the script did not run. `report.py` counts that as refused.
* **Measure against the compositor's own idea of the screen.** Nested in Xvfb, Cinnamon's output is 800x600 on a 1024x768
  Xvfb screen; compare a capture with the shell's stage size.
* **A test device can be the bug.** WirePlumber never showed the `vivid` camera because PipeWire misreads one of vivid's
  test controls ([Camera: the capture nodes only](../decisions/desktop/camera.md)); check the device before blaming the code under test.
* **Names are case-sensitive.** `org.Cinnamon` (the shell) and `org.cinnamon.Muffin` (the compositor) are different
  families; a blocklist entry covers only its own spelling.
* **The bus filter works on names; the risk is per connection.** One process owns many names on one connection, and a call
  to any of them reaches all of its objects (`shared_connection.py`).

## What this does not cover

Headless or nested compositors in virtual machines, with default configuration: no logged-in desktop, no session manager,
no extensions, no portal backends or consent dialogs, no clipboard managers. A real session can add bus names and
services (GNOME Shell may own `org.freedesktop.Notifications` there; the headless one did not). Those checks are manual,
on a real machine, and are listed as such in ASSESSMENT.md and CLAUDE.md.
