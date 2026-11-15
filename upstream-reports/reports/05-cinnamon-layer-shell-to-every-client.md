# 05. Cinnamon 6.8: zwlr_layer_shell_v1 is offered to every client

| | |
|---|---|
| Target | Cinnamon: `github.com/linuxmint/cinnamon` (the compositor is Muffin: `github.com/linuxmint/muffin`) |
| Measured | Cinnamon 6.8.0 (Fedora 45); Cinnamon 6.4.10 and 6.4.13 do not list it (the control) |
| Class | any client can draw over the desktop |
| Our severity | medium (a full-screen opaque surface on top of the user's windows) |
| Suggested channel | public issue (verify the project's security policy first) |
| Review | pending |
| Filed | not filed |

## Issue text

**Title:** Cinnamon 6.8 (Wayland) offers `zwlr_layer_shell_v1` to every client

Cinnamon 6.8.0's Wayland socket lists `zwlr_layer_shell_v1`; 6.4 does not. Any client can bind it and place a surface in a layer
of its choosing. Measured, nested in a private Xvfb with a screenshot taken through Cinnamon's own screenshot service as the
observer: `swaybg -c '#ff00ff'` (a plain layer-shell client) stays up and paints 94.7 % of the screen with its colour; the
capture before starting it has none of that colour.

A layer surface on the overlay layer can cover every window, and the protocol allows exclusive keyboard interactivity
(not tried here). If the layer shell is meant for Cinnamon's own panels and desktop, offering it only to trusted clients
(by executable, or not at all on a restricted socket) would keep an application from painting over the desktop.

### Reproduce

`tests/compositors/layer_shell.py` in the repository named below starts Cinnamon in a private Xvfb, takes a capture, starts
`swaybg`, takes a second capture, and prints the share of the colour in each.

## Evidence and reproduction in the repository

* `upstream-reports/reproduce.sh 05` (fedora for 6.8; debian and ubuntu print the 6.4 control: the global is not listed).
* Saved results: `docs/compositor-assessment/results-fedora-45.json` (`cinnamon` registry), `rule-a-fedora-45.json`.

## Reviewer notes (not posted)

* The observation uses Cinnamon's own screenshot service, which any client of the session bus can call (report 11); it is only the
  eyes of the test.
* Exclusive keyboard interactivity was not tried. Do not claim it.
