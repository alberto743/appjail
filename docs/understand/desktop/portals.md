# Portals

*Part of [Desktop access](index.md). Previous: [D-Bus and the filtering proxy](dbus.md). Next: [audio](audio.md).*

## What it is

**XDG desktop portals** are D-Bus interfaces through which a sandboxed app asks the desktop to do something on its
behalf, with you deciding. The app calls `org.freedesktop.portal.Desktop`; the portal service, `xdg-desktop-portal`,
passes the request to a *backend* for your desktop (GNOME, KDE, GTK, wlroots), which shows its own dialog. The best
known is the **file chooser**: the app asks for a file, you pick one in a dialog the app does not control, and the app
receives that file and nothing else, through the **document portal**, a small filesystem that exposes only the files
you chose. Other portals cover notifications, opening links in another app, printing, screenshots and screen casting,
the camera, the appearance settings and more. Decisions you take (allow the camera, a screen-cast source) are kept in a
**permission store**.

To know who is asking, `xdg-desktop-portal` identifies the calling process's sandbox: it understands Flatpak (a
`.flatpak-info` file in the root of the caller), Snap and Linyaps. A caller it does not recognise is a host
application, with nothing to restrict.

## Why it matters

Portals invert the usual question. Instead of "may this app read my Documents folder?", the app may ask for one
document, and the answer is your choice in the dialog. That is the only way to give an app a file it needs without
deciding in advance which folder it may see. But a portal can only restrict an app it recognises as sandboxed, and only
offer the dialogs its backend implements.

## How appjail uses it

- **`portals = true`** gives the app a **safe set** through the [filtering proxy](dbus.md). Everything else on the
  portal's name is invisible.
- **Opt-in interfaces** that give more must be named one by one, with a warning. Spawning commands on the host and
  installing launchers are never available. Each portal of the three groups is described
  [below](#the-portals-appjail-knows).
- **An identity the portal understands.** appjail writes a Flatpak-style identity for each running app: the file the
  portal reads, with the application id `app.appjail.NAME`, and the jail's process id taken from bubblewrap. The id is
  the portal's whole notion of who the app is, so two apps must never share one: in each dot-separated part of the name,
  `_` becomes `_u`, `-` becomes `_h`, an empty part becomes `_e`, and a part starting with a digit gets a leading `_`
  (`my-app` is `app.appjail.my_happ`, `7zip` is `app.appjail._7zip`). It goes into the *proxy's* jail, because the
  proxy's connection is what the portal sees as the caller, never into the app's, so the app can neither read nor forge
  it. Nothing depends on Flatpak; this is a compatibility shim.
- **The document portal** is started if needed, and only the app's own view of it is bound into the jail.
- **Taking back.** `appjail portals NAME` lists the files the app received and revokes them (`--revoke`,
  `--revoke-all`), through the portal itself, so the files disappear from the app's view at once. `remove` also deletes
  the app's remembered portal decisions, so a later app with the same name starts with none.

### The portals appjail knows

The names are the part after `org.freedesktop.portal.`. "Dialog" says what the portal documentation states about asking
you; a backend may ask more or less, and where the documentation is silent the table says so.

#### Safe set (`portals = true`)

| Portal | What the app can do | Dialog |
| --- | --- | --- |
| `FileChooser` | Ask you to open files, save a file or pick a folder. The app gets only what you chose, often through the document portal, and keeps access across sessions. | A file chooser the app does not control |
| `Notification` | Send and withdraw notifications, with icons, sounds and buttons. Clicking one after the app exited starts it again. | None |
| `Settings` | Read a few desktop settings: colour scheme, accent colour, contrast, reduced motion. Read-only. | None |
| `Trash` | Move a file to the trash, only a file it can already open for writing. | None stated |
| `Print` | Print a file it already has open, after choosing settings. | A print dialog |
| `Inhibit` | Hold off logout, user switch, suspend or idle (a video player keeping the screen on), and learn that the session is ending. | None stated |
| `NetworkMonitor` | Read whether the network is up, metered, and whether a host and port are reachable. | None |
| `ProxyResolver` | Ask which proxy to use for an address. | None |
| `Secret` | Receive one master secret of its own, to encrypt its own data. It does not reach your keyring's other entries. | None stated |
| `Realtime` | Ask for real-time or high priority scheduling for a thread, within the limits RealtimeKit sets. | None |
| `MemoryMonitor` | Be told that memory is low (a level from 0 to 255). | None |
| `PowerProfileMonitor` | Read whether power-saver mode is on. | None |

Of these, only `FileChooser` and `Print` ask you; the rest reveal little or act only on what the app already holds.
The document portal comes with the set.

#### Opt-in (`portal_interfaces`)

Each needs its name in `portal_interfaces` and raises a warning when you grant it.

| Portal | What the app can do | Dialog |
| --- | --- | --- |
| `OpenURI` | Open a link, a file or the folder holding a file in another application. | Optionally asks which application |
| `Email` | Have your mail client compose a message with recipients, subject, body and attachments. | A compose window |
| `Screenshot` | Take a screenshot of the screen, a window or an area, and pick a colour. The image may arrive through the document portal. | The documentation names an interactive option but no consent prompt |
| `ScreenCast` | Receive the screen or a window as a PipeWire video stream; a restore token can skip the dialog later. | A source selection dialog |
| `RemoteDesktop` | Control the keyboard, pointer and touchscreen, optionally with screen and clipboard. | A dialog choosing devices and content |
| `GlobalShortcuts` | Bind shortcuts that fire whatever window has focus. | A dialog to configure the shortcuts |
| `InputCapture` | Capture keyboard and pointer input at screen edges (the way a keyboard-sharing tool works). The compositor can stop it at any time. | A dialog allowing the capture |
| `Camera` | Ask for camera access and receive a PipeWire connection to the camera. Binds no device: see [GPU and camera](devices.md). | Not described by the portal documentation |
| `Location` | Receive your coordinates, accuracy, speed and heading as they change. | None stated |
| `Account` | Read your user id, name and avatar. | A dialog may show the app's reason |
| `Wallpaper` | Set the desktop or lock-screen wallpaper. | None stated; a preview may show |
| `Background` | Ask to keep running in the background and to start at login. See the Limits about `flatpak run`. | None stated |
| `Usb` | List, watch and open USB devices, each handed over as a file descriptor. Needs a general permission and one per device. | A prompt to allow or deny each device |

#### Never available

| Portal | Why it is refused |
| --- | --- |
| `Flatpak` | It spawns commands on the host outside the jail, which would end the confinement. |
| `DynamicLauncher` | It installs launcher files that run on your desktop, outside the jail, and rewrites their command for Flatpak apps. |

Asking for either in `portal_interfaces` is an error, as is any name not listed above.

## Connections

- Portals travel on D-Bus, through the same proxy: [D-Bus and the filtering proxy](dbus.md).
- The Camera portal is how apps that use PipeWire reach a camera: [GPU and camera](devices.md).
- The Settings portal carries the dark-mode preference: [Appearance](../../guide/appearance.md).
- Decision: [A Flatpak identity for the portals](../../decisions/desktop/portal-identity.md).

## Limits

- The protection of each opt-in interface depends on the backend asking you. Only the GTK backend has been tested; the
  GNOME and KDE backends and their dialogs have not, and backends differ in what they implement.
- The permission store and the Background portal treat the app as a Flatpak app (an autostart entry would say
  `flatpak run`, which does nothing without Flatpak).
- The document portal needs FUSE.

## References

- [XDG Desktop Portal documentation](https://flatpak.github.io/xdg-desktop-portal/docs/), including
  [FileChooser](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.FileChooser.html),
  [Documents](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Documents.html) and
  [Settings](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Settings.html).
- The per-portal tables follow the interface pages of the same documentation, named
  `doc-org.freedesktop.portal.NAME.html` (for example
  [ScreenCast](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html) and
  [DynamicLauncher](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.DynamicLauncher.html)).
  The documentation has no page for `Flatpak`; that row rests on what the interface does (it starts processes on the
  host), not on a cited page.
