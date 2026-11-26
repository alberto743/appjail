# Wayland compositors

Whether an app with a window runs without `full_wayland` depends on your compositor: appjail refuses an app whose
Wayland socket offers privileged interfaces (screen capture, typing into other windows, reading the clipboard without
focus, controlling other windows), or interfaces it does not know. Why: [Wayland](../understand/desktop/wayland.md).

| Desktop or compositor (measured versions) | Apps run without `full_wayland` |
|---|---|
| GNOME 48.7, 50.1, 51.1 | yes |
| Cinnamon 6.4 | yes |
| Cinnamon 6.8 | no: it offers layer shell, which lets an app draw over the desktop |
| sway 1.10, 1.11, 1.12 | yes |
| labwc 0.8, 0.9, 0.20 | yes |
| Hyprland 0.55 | yes |
| KDE Plasma (KWin 6.3, 6.6, 6.8) | no: its app socket still offers the layer shell and shell control (6.3 and 6.6 also clipboard reading without focus) |
| Hyprland 0.53 | no: virtual keyboard and pointer |
| Wayfire, Cage, Weston 14, 15 | no: capture, input and window control |

Copy and paste with the keyboard focus works everywhere.

## When an app is refused

The message names the interfaces and what they would allow. If you accept that for this app:

```sh
appjail perms NAME --allow full_wayland
```

The app then runs, with a warning at each start. On KDE Plasma this is needed for every app until KWin hides the layer
shell, the Plasma shell, output management, the appmenu manager and the desktop controls on restricted sockets.

If the message says an interface is **not known to appjail**, your compositor offers something that has not been
classified yet (a compositor that was not measured, or a new version). `full_wayland` lets the app run meanwhile; please
[report](https://github.com/alberto743/appjail/issues) the interface name and your compositor's version so it can be
classified.

## Compositors not measured

niri, river, COSMIC, Mir and others are decided by what their socket lists when the app starts. How a compositor is
measured: [assessing a compositor](../develop/assessing-compositors.md).
