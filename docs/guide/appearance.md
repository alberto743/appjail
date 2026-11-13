# Appearance: theme, dark mode, fonts, cursor

An app in a jail does not see your home, your environment variables or your desktop's settings database, so it may
not look like your other apps: a light theme in a dark desktop, a different cursor, missing fonts. This page explains
why, and how to bring the look back without opening more than needed.

## Why an app can look different

Toolkits find their appearance in several places, and the jail hides most of them on purpose:

| Where toolkits look | In the jail |
|---|---|
| The **Settings portal** (dark or light preference, accent colour; on GNOME also theme, icon, cursor and font names) | available with `--allow portals` |
| The desktop's settings database (`dconf` on GNOME, through D-Bus) | refused: writing it can set shortcuts that run commands ([why](../decisions/desktop/dbus-refused.md)) |
| Environment variables (`GTK_THEME`, `XCURSOR_THEME`, `QT_QPA_PLATFORMTHEME`, ...) | cleared: no variable of yours reaches the app |
| Files in your home (`~/.config/gtk-3.0`, `~/.config/kdeglobals`, `~/.local/share/fonts`, `~/.themes`, ...) | not visible; the app has a private home of its own |
| System-wide themes, icons, cursors and fonts (`/usr/share/themes`, `/usr/share/icons`, `/usr/share/fonts`, `/etc/fonts`) | visible, read-only |
| The compositor (scaling, and the cursor for apps that let the compositor draw it) | available: these interfaces are on the app's Wayland socket |

So an app always has the themes, icons, cursors and fonts installed system-wide; what it lacks is *which* of them you
chose, and anything you installed only in your home.

## Dark mode

Give the app the portals:

```sh
appjail perms NAME --allow portals
```

The portals' safe set includes Settings, which answers the `color-scheme` preference (dark, light or none). Toolkits
that read it follow your desktop's choice: GTK 4 and libadwaita apps, Qt 6 apps, Chromium and Electron apps, Firefox.
appjail's tests check that the Settings portal answers through the jail's proxy; whether an app follows the answer is
up to its toolkit. The same permission also gives the app the file chooser and notifications through the portals.

For an app whose toolkit does not read the portal, set the preference in its own configuration, in its private home
(next section).

## A theme, cursor or font setting for one app

The app's private home is `~/.local/share/appjail/apps/NAME/home` on your side and `/home/app` in the jail. Toolkit
configuration placed there is read by the app as its own:

```sh
home=~/.local/share/appjail/apps/NAME/home
mkdir -p "$home/.config/gtk-3.0"
cat > "$home/.config/gtk-3.0/settings.ini" <<'EOF'
[Settings]
gtk-application-prefer-dark-theme=1
gtk-theme-name=Adwaita
gtk-icon-theme-name=Adwaita
gtk-cursor-theme-name=Adwaita
gtk-font-name=Cantarell 11
EOF
```

The names must be of themes, icons, cursors and fonts installed system-wide (under `/usr/share`), or in a folder you
grant (below). The same works for `gtk-4.0/settings.ini`, and for KDE and Qt apps by copying your `~/.config/kdeglobals`
into the app's `~/.config`. A copy is better than a grant of the original: the app then cannot change your desktop's
settings, and you choose what it learns.

## Themes and fonts installed in your home

Themes, icons and fonts you installed for yourself rather than system-wide can be granted read-only:

```sh
appjail perms NAME --add-dir ~/.local/share/fonts      # your own fonts
appjail perms NAME --add-dir ~/.local/share/themes     # GTK themes (or ~/.themes)
appjail perms NAME --add-dir ~/.local/share/icons      # icon and cursor themes (or ~/.icons)
```

They appear at the same place in the app's home, where the toolkits look for them. Keep them read-only: write access
to the icon folders is refused, because the desktop decodes icons outside any jail. Granting `~/.config/gtk-3.0` itself
is possible but also shows the app your bookmarked folders; prefer the copy above.

## Scaling and cursor

Wayland apps get the scale of each screen from the compositor, so HiDPI and fractional scaling work as for any app.
Apps that use the cursor-shape protocol let the compositor draw the cursor, which then matches your desktop; others draw
it themselves from the cursor theme their settings name, or a default one.

X11-only apps run on a private Xwayland. In the rootless mode (`display = xwayland`) they are scaled by the compositor
and can look blurry on a scaled screen; in the rootful mode (`xwayland-rootful`) they live in one window whose size is
set with `--display-size WxH`.

## What does not work

- Changing the theme while the app runs, through the desktop's settings, reaches only toolkits that follow the Settings
  portal (and only with `portals`).
- Variables such as `GTK_THEME` cannot be passed to the app: the environment is always cleared. Use the settings files
  above.
