# Related projects

*Decision on [the project](index.md). Facts as found on each project's page in November 2026; check them before relying
on them. None of these was installed or run.*

appjail covers one niche: AppImages from a source you name, pinned by hash, each in its own bubblewrap jail, with
updates held in quarantine. Other tools cover other parts of this; if one fits you better, use it.

## Managing AppImages

| Project | Language, licence | What it does | Relation to appjail |
|---|---|---|---|
| [AM / AppMan](https://github.com/ivan-hc/AM) | shell, GPL-3.0 | thousands of install scripts for AppImages and portable programs | appjail's catalog is derived from its list through appjail-db; appjail never runs its scripts. AM updates itself and fetches scripts from its main branch; sandboxing is optional |
| [Soar](https://github.com/pkgforge/soar) | Rust, MIT | package manager for static binaries and AppImages; GitHub, GitLab, Codeberg and Forgejo releases; checksums and signatures | some Landlock sandboxing; no update delay found |
| [AppManager](https://github.com/kem-a/AppManager) | Vala/GTK, GPL-3.0 | installs AppImages with a private home and a bubblewrap sandbox with a D-Bus proxy | the closest in spirit; a desktop app around files you already have rather than pinned releases |
| [Gear Lever](https://github.com/mijorus/gearlever) | Python/GTK, GPL-3.0 | menu integration and updates | no sandbox of its own found |
| [Zap](https://github.com/srevinsaju/zap) | Go, MIT | installs from GitHub releases and URLs; delta updates from embedded update information | last updated June 2024 |
| [Bread](https://github.com/pegvin/bread), [appimage-cli-tool](https://github.com/AppImageCrafters/appimage-cli-tool) | | small CLIs to install, update and remove AppImages | last updated 2024 and 2023 |
| [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher), [appimaged](https://github.com/probonopd/go-appimage) | | desktop integration for AppImages you have | no sandbox |
| [AppImageUpdate](https://github.com/AppImageCommunity/AppImageUpdate) | | delta updates driven by the AppImage's update information | appjail ignores that information |

## Sandboxing

| Project | What it is | Relation to appjail |
|---|---|---|
| [Flatpak](https://flatpak.org/) | runtimes, portals, signed repositories | the mature route when an app is on Flathub; appjail writes a Flatpak-style identity only so the portals recognise its jail |
| [sas](https://github.com/Samueru-sama/simple-appimage-sandbox), [aisap](https://github.com/mgord9518/aisap) | bubblewrap wrappers for AppImages you have | neither fetches, pins or updates; sas leaves sockets and the network on by default |
| [FlatImage](https://github.com/flatimage/flatimage) | a different format, sandboxed by default | not an AppImage manager |
| [Bubblejail](https://github.com/igo95862/bubblejail) | bubblewrap profiles and a GUI for any desktop app | not AppImage-specific; fetches nothing |
| [Firejail](https://github.com/netblue30/firejail) | set-uid sandbox with 900+ profiles | appjail uses unprivileged bubblewrap ([why](../isolation/bubblewrap.md)) |
| [bubblewrap](https://github.com/containers/bubblewrap), [nsjail](https://github.com/google/nsjail), [Landrun](https://github.com/Zouuup/landrun) | building blocks | appjail drives bubblewrap, and uses one Landlock feature |

## Installing release binaries

[eget](https://github.com/zyedidia/eget) (checks a published `.sha256`), [bin](https://github.com/marcosnils/bin),
[ubi](https://github.com/houseabsolute/ubi) (`--min-age-days`, the only quarantine-like feature found) and
[dra](https://github.com/devmatteini/dra) download the right asset of a release; none sandboxes it.

## Same name, unrelated

[AppJail](https://github.com/DtxdF/AppJail) is a framework for FreeBSD jails; this project is not affiliated with it.

## Sources and re-checks

Written from each project's GitHub page and website, read in November 2026; commit dates are not shown on those pages,
so activity claims are limited to what a release page or search listing showed. Re-checked for the 0.4 release through
the GitHub API (language, licence, last push, archived, moved), and again for the 0.5 release (2026-11-13) for all 21
GitHub projects listed: no language, licence or activity claim changed, none is archived or moved. The feature claims
were not re-read. Re-check this page, and its date, at each minor release.
