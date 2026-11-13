# Desktop access

A desktop app is useful because it talks to the rest of the desktop: it draws windows, plays sound, opens files you
choose, sends notifications, reaches the network. Each of these is a channel to something outside the jail, and each
channel is also a way out: the same socket that lets an app draw a window may let it capture the screen; the same bus
that carries a notification can reach the service that runs commands. This part explains each channel, what an
unrestricted one would allow, and how appjail narrows it.

## The channels

<figure>
<svg viewBox="0 0 720 430" role="img" aria-labelledby="dk-title dk-desc" style="max-width:100%;height:auto;font-family:inherit">
  <title id="dk-title">The channels between an app jail and the desktop</title>
  <desc id="dk-desc">The app jail on the left; each channel to the desktop on the right passes a check or a helper that narrows it: the registry rule on the Wayland socket, a private Xwayland inside the jail, the D-Bus proxy in its own jail, the portal identity, the private audio graph in its own jail, pasta for the network, and only the device nodes granted.</desc>
  <style>
    .dk-jail { fill: var(--md-code-bg-color, #f2f4f7); stroke: var(--md-accent-fg-color, #0284c7); stroke-width: 1.6; }
    .dk-help { fill: var(--md-code-bg-color, #f2f4f7); stroke: var(--md-accent-fg-color, #0284c7); stroke-width: 1.4; stroke-dasharray: 6 3; }
    .dk-host { fill: var(--md-default-bg-color, #fff); stroke: var(--md-default-fg-color--light, #777); stroke-width: 1.3; }
    .dk-t { fill: var(--md-default-fg-color, #222); font-size: 14px; font-weight: 600; }
    .dk-s { fill: var(--md-default-fg-color--light, #555); font-size: 12px; }
    .dk-l { stroke: var(--md-default-fg-color--light, #777); stroke-width: 1.4; fill: none; }
  </style>
  <rect class="dk-jail" x="10" y="10" width="170" height="410" rx="10"/>
  <text class="dk-t" x="26" y="40">App jail</text>
  <text class="dk-s" x="26" y="60">the app, and inside it</text>
  <text class="dk-s" x="26" y="76">a private Xwayland</text>
  <text class="dk-s" x="26" y="92">for X11-only apps</text>
  <rect class="dk-help" x="230" y="22" width="220" height="44" rx="6"/>
  <text class="dk-t" x="242" y="41">registry rule</text>
  <text class="dk-s" x="242" y="58">no privileged interfaces</text>
  <rect class="dk-host" x="500" y="22" width="210" height="44" rx="6"/>
  <text class="dk-t" x="512" y="49">compositor (Wayland)</text>
  <rect class="dk-help" x="230" y="80" width="220" height="44" rx="6"/>
  <text class="dk-t" x="242" y="99">D-Bus proxy (own jail)</text>
  <text class="dk-s" x="242" y="116">only the granted names</text>
  <rect class="dk-host" x="500" y="80" width="210" height="44" rx="6"/>
  <text class="dk-t" x="512" y="107">session bus</text>
  <rect class="dk-help" x="230" y="138" width="220" height="44" rx="6"/>
  <text class="dk-t" x="242" y="157">portal identity</text>
  <text class="dk-s" x="242" y="174">app.appjail.NAME, safe set</text>
  <rect class="dk-host" x="500" y="138" width="210" height="44" rx="6"/>
  <text class="dk-t" x="512" y="165">desktop portals</text>
  <rect class="dk-help" x="230" y="196" width="220" height="44" rx="6"/>
  <text class="dk-t" x="242" y="215">private audio graph</text>
  <text class="dk-s" x="242" y="232">a speaker; a mic only with mic</text>
  <rect class="dk-host" x="500" y="196" width="210" height="44" rx="6"/>
  <text class="dk-t" x="512" y="223">your audio server</text>
  <rect class="dk-help" x="230" y="254" width="220" height="44" rx="6"/>
  <text class="dk-t" x="242" y="273">pasta</text>
  <text class="dk-s" x="242" y="290">outbound only, not your host</text>
  <rect class="dk-host" x="500" y="254" width="210" height="44" rx="6"/>
  <text class="dk-t" x="512" y="281">the internet</text>
  <rect class="dk-help" x="230" y="312" width="220" height="44" rx="6"/>
  <text class="dk-t" x="242" y="331">device binds</text>
  <text class="dk-s" x="242" y="348">render nodes, capture nodes</text>
  <rect class="dk-host" x="500" y="312" width="210" height="44" rx="6"/>
  <text class="dk-t" x="512" y="339">GPU, camera</text>
  <rect class="dk-help" x="230" y="370" width="220" height="44" rx="6"/>
  <text class="dk-t" x="242" y="389">menu entry by appjail</text>
  <text class="dk-s" x="242" y="406">appjail run, one file per open</text>
  <rect class="dk-host" x="500" y="370" width="210" height="44" rx="6"/>
  <text class="dk-t" x="512" y="397">application menu</text>
  <path class="dk-l" d="M180 44 H230 M450 44 H500"/>
  <path class="dk-l" d="M180 102 H230 M450 102 H500"/>
  <path class="dk-l" d="M180 160 H230 M450 160 H500"/>
  <path class="dk-l" d="M180 218 H230 M450 218 H500"/>
  <path class="dk-l" d="M180 276 H230 M450 276 H500"/>
  <path class="dk-l" d="M180 334 H230 M450 334 H500"/>
  <path class="dk-l" d="M180 392 H230 M450 392 H500"/>
</svg>
<figcaption>Only the window channel exists by default. Every other channel exists only when the manifest grants it, and
always passes through the narrowing shown in the middle.</figcaption>
</figure>

## The pages

1. **[Wayland](wayland.md)**: the display protocol, its privileged interfaces, and the rule that reads what the app's
   socket offers.
2. **[X11 and the private Xwayland](xwayland.md)**: why the host's X server is never shared, and how X11-only apps get a
   server of their own.
3. **[D-Bus and the filtering proxy](dbus.md)**: the session bus, why names alone are not enough, and confined
   services.
4. **[Portals](portals.md)**: dialogs the app does not control, and how the portals recognise a jailed app.
5. **[Audio](audio.md)**: why the host's sound sockets cannot be shared, and the private graph each app gets instead.
6. **[GPU and camera](devices.md)**: which device nodes are bound, and why only those.
7. **[Network](network.md)**: the private network namespace, the host network, and the LAN.
8. **[Menu entries and opening files](menu-entries.md)**: integrating with the desktop's menu without letting the
   AppImage decide what runs.

How-to pages: [D-Bus and portals](../../guide/dbus.md), [Appearance](../../guide/appearance.md). The decisions behind
this part are in [Decisions: desktop access](../../decisions/desktop/index.md).

## A pattern across the channels

Three ideas recur on every page:

- **What decides is what the channel lets a client do**, measured where possible, not what a name or a protocol
  promises. The Wayland rule reads the socket's registry; the D-Bus check reads who owns a name; the audio graph is
  inspected after it starts.
- **Where the host cannot restrict a client, appjail gives the app a private copy** of the service instead of a share
  of the host's: a private Xwayland, a private audio graph, a private network namespace.
- **The host's services trust their clients by identity**, and an app in a jail has none they recognise. PipeWire and
  xdg-desktop-portal restrict only clients they know to be sandboxed (Flatpak, Snap). That fact shapes the audio, camera
  and portal designs.
