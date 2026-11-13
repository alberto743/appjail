# The Wayland socket is judged by what it lists

*Decision on [desktop access](index.md).*

**Context.** Wayland clients reach everything through interfaces (globals) that the compositor lists on its socket.
Some are privileged: screen capture, virtual keyboards and pointers, reading the clipboard without focus, controlling
other windows or the desktop. The `wp_security_context_v1` protocol lets a sandbox ask the compositor for a restricted
socket. A first rule refused apps wherever that protocol was missing; it rested on a wrong claim that GNOME implements
it. Measurements of nine compositors on Debian 13 and Ubuntu 26.04 showed instead:

- GNOME (Mutter, GNOME Shell) and Cinnamon (Muffin) have no such protocol, and their own socket lists nothing
  privileged: they keep capture and remote input on D-Bus;
- the protocol is not sufficient: KWin's restricted socket still lists data-control, and a client read another
  client's clipboard through it; Hyprland 0.53's lists virtual input, and a client typed through it;
- sway, labwc and Hyprland 0.55 hide every privileged interface on the restricted socket.

**Options.** Decide by compositor name; decide by the presence of the protocol; decide by what the app's socket
actually lists.

**Decision.** Before starting anything, `run` reads the registry of the socket the app will get (the restricted one
where the compositor offers it, else the compositor's own) and refuses a windowed app when it lists a privileged
interface, naming it and what it allows. The manifest permission `full_wayland` accepts the risk: the app then runs
with a warning. It is a permission, not a run option, so menu entries and file opening work for an app you decided
about, and so a warning that scrolls past is never taken for consent.

**Consequences.** Apps run on GNOME, Cinnamon, sway, labwc and Hyprland 0.55 without the permission. **KWin is
refused**, like any compositor whose app socket lists a privileged interface: accepting data-control there would grant
what `full_wayland` grants without asking, and would go stale with KWin. Plasma users need `full_wayland` per app until
KWin hides data-control. Ordinary copy and paste is not affected anywhere: it uses the core clipboard, which needs
keyboard focus (measured on every compositor, in both directions). The measurements are of headless compositors, not
of full desktop sessions.

**Revisit when** KWin hides data-control on restricted sockets, or a narrower grant for the clipboard alone is wanted.
