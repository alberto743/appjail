# Deferred and planned work

What has been decided *not yet*, with the reason and the condition for taking it up. Each item has its full reasoning
on the decision page linked.

## Open work

Every open item is one row with one status. The status says what unblocks it; the table is sorted by how close each
item is to being taken up. No planned code work is pending: nothing below is started without the maintainer.

- **Scheduled**: the maintainer set a date or an event.
- **Waiting**: an outside event, not under the maintainer's control.
- **Recurring**: done again at every occurrence of the event.
- **Undecided**: the maintainer's call, with no date.
- **Paused**: evaluated, then stopped by the maintainer.
- **Deferred**: a feature not built now, with the condition for taking it up.

| Item | Status | Waiting on | Next step, or why not now | Reasoning |
|---|---|---|---|---|
| Workflows on `ubuntu-latest` | Scheduled | December 2026, when GitHub's move to Ubuntu 26.04 completes (planned for 2026-11-19) | Switch the workflows from `ubuntu-26.04` to `ubuntu-latest` and check CI. `check-platforms.yml` then has no runner label to read for Ubuntu (its script skips that check), so give it another target | [workflows](project/workflows.md) |
| Camera portal measurement on Debian and Ubuntu | Waiting | a PipeWire release after 1.6.2 with the V4L2 fixes (`6734d69c`, `919de4c5`), packaged by Debian and Ubuntu | Re-run the measurement and let the session manager link the `vivid` test camera instead of `pw-link`. Check the release notes; nothing to do before. Done on Fedora 45 (PipeWire 1.6.11); the test skips on Debian and Ubuntu until they package a PipeWire that reads the control | [camera](desktop/camera.md), [measurements](../develop/camera-audio-evidence.md#the-v4l2-node-and-wireplumber-explained-a-test-control-of-vivid), [Fedora 45](../develop/camera-audio-evidence.md#fedora-45-measured-2026-11-14) |
| Re-check related projects and references | Recurring | each minor release | Re-check the facts on related projects and the references cited on the concept pages | [related projects](project/related-projects.md) |
| Reporting upstream the crashes found while measuring | Undecided | the maintainer | Muffin and Cinnamon on `wl-copy`/`wl-paste`, Hyprland 0.53.3 when a window closes | [assessment](../compositor-assessment/ASSESSMENT.md) |
| Accessibility bus for screen readers | Undecided | the maintainer | `org.freedesktop.a11y` is refused, so screen readers cannot reach a jailed app. Flatpak proxies the accessibility bus with fixed `--call` and `--broadcast` rules for `org.a11y.atspi.Registry`; an opt-in permission could do the same, with the proxy in its own jail | [Flatpak compared](project/flatpak-comparison.md) |
| A narrower view of the host's system | Undecided | the maintainer | The host's `/usr`, `/lib*` and part of `/etc` are bound read-only, so an app can list installed software and reach every host library. A runtime is out of scope; binding only what the AppImage needs could be studied | [Flatpak compared](project/flatpak-comparison.md) |
| URL handlers | Undecided | the maintainer | Menu entries declare file types (`desktop --mime`) but never `x-scheme-handler/`, so a jailed app is never offered to open a link. `appjail open` already binds one file alone and could back them | [Flatpak compared](project/flatpak-comparison.md) |
| Other architectures (arm64) | Paused | the maintainer resumes it | Evaluated: moderate code, expensive verification | [platform](project/platform.md) |
| GPG tier (tier 2) | Deferred | a wanted app signs with GPG and has no attestation | A signature proves a key, not its owner; it needs a per-app key pin, a jailed `gpgv` and update rules, while attestations and the quarantine hash already cover attested and unattested apps | [evidence tiers](acquisition/evidence-tiers.md) |
| Resolvers for other forges (GitLab, Codeberg/Forgejo, SourceForge, vendor sites) | Deferred | a wanted app is released only on another forge | Only GitHub is supported; other forges offer no per-asset digest or attestations, so tier 4 at best. In November 2026 the appjail-db catalog listed 13 apps on GitLab or Forgejo and about 180 pointing to vendor sites | [sources](acquisition/sources.md) |
| An allowlisting proxy for the LAN | Deferred | host filtering for `network` is wanted | With `network`, other hosts on the LAN stay reachable; attacks on them are outside the threat model | [network](desktop/network.md) |
| A restricted camera connection for apps that use PipeWire without the portal | Deferred | a wanted app needs a PipeWire camera and does not use the portal | Such an app sees only the private audio graph, which has no camera. appjail could call the portal for it and hand it the restricted connection as its `pipewire-0`; that needs a relay and a way to merge it with the private graph, and nothing measured shows an app that needs it. Webcamoid is not one: its V4L2 plugin works and its PipeWire plugin does not load | [camera](desktop/camera.md) |
| A filtering Wayland proxy | Deferred | Plasma users or the GNOME GPU descriptor are judged to cost more than a new proxy; or a compositor hides the globals itself | appjail can only look at an app's socket, not shape it, so every privileged global a compositor leaves on it refuses the app (KWin's layer shell, Plasma shell, output management, appmenu and desktop controls) and two allowed globals stay visible (GNOME's DRM file descriptor and `gtk_shell1`'s focus requests). A proxy would drop them and refuse a bind to them (enforcement instead of refusal), which would let KDE Plasma apps run without `full_wayland`. It parses untrusted client bytes and passes file descriptors, so it would run in a jail of its own, as `xdg-dbus-proxy` does, and it adds code to a stdlib-only tool | [Unknown Wayland interfaces are refused](desktop/wayland-allowlist.md) |
| A pty proxy for terminal apps | Deferred | terminal apps are often granted `raw_terminal`, or the grant proves too coarse | Give the app a pseudo-terminal of its own and pass its output through a byte-level filter that keeps what drawing needs (colours, cursor movement, erase, charsets, alternate screen, mouse modes, title push and pop) and drops OSC, DCS, APC, PM, SOS, C1 controls and the queries whose replies reach your input, forwarding keystrokes and window-size changes, so terminal apps need no grant. Measured: htop sends none of the dropped classes. Costs: a state machine on untrusted bytes (sequences split across reads), which belongs in a jail of its own like `xdg-dbus-proxy`, an allow-list to keep right as terminals add extensions, and an app that sees a different pty from yours | [terminal output](isolation/terminal-output.md) |

## Not yet verified

Checks that need hardware, a desktop session or a network the test guests do not have. They are manual checks on a real
machine.

- Portals: the GNOME and KDE backends and their interactive dialogs (only the GTK backend is tested), and revoking a
  camera or screen share in the desktop's privacy settings.
- Compositors: a full desktop session (GNOME, Plasma, Cinnamon) with its daemons, the bus names they add and the Wayland
  globals they list; only headless or nested compositors were measured
  ([what the assessment does not cover](../develop/assessing-compositors.md#what-this-does-not-cover)).
- Camera: whether Webcamoid fixes its device listing (its V4L2 plugin lists `/dev` by file type, see [GPU and
  camera](../understand/desktop/devices.md#limits)); a capture from a real webcam (a laptop camera was used only for the
  listing), unplugging while the app runs, and a real camera through the Camera portal.
- Xwayland: GPU acceleration; clipboard and drag and drop through the `xwayland-rootful` window (briefly tested on
  GNOME).
- D-Bus: real MPRIS players and tray icons with process-id names.
- Audio: a real headset and microphone, the desktop's microphone indicator; two apps at once.
- Network: IPv6 over a real internet route (tested only on a simulated network).
