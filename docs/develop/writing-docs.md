# Writing the documentation

The site is written in Markdown under `docs/` and built with [Zensical](https://zensical.org/) from `zensical.toml`.
It is a single connected text: every page says where it sits in the argument, and links backward and forward.

## Building

```sh
tests/vm/docs.sh                # builds in the guest, strict; the result is in vm/<guest>/site
```

The build is strict: a link to a missing page or anchor fails it. The tooling is pinned with hashes in
`.github/requirements-docs.txt` and never becomes a dependency of appjail. The site loads nothing from other servers:
no web fonts, no CDN scripts, no emoji images, no maths renderer; keep it that way (diagrams are inline SVG).

An inline SVG goes in a plain `<figure>` (no `markdown` attribute), with no blank line inside it and its `<desc>` on one
line: Markdown processing would otherwise insert a `<br />`, and a `<br>` inside SVG makes the browser close the SVG,
so nothing is drawn. Colours come from the theme's CSS variables, so the diagram follows light and dark mode.

The logo in `docs/assets/` is a copy of `assets/logo-light.svg` (`logo.svg`, used in the header and on light pages) and
`assets/logo-dark.svg`; the colours in `docs/stylesheets/appjail.css` are the logo's. Change them together.

## Structure

| Section | Holds | Tense and voice |
|---|---|---|
| Understanding appjail | the problem, the principles, and one page per concept, by topic | present tense, explanatory |
| Guide | tasks: what to type and what it does | imperative, short |
| Decisions | one page per decision: context, options, decision, consequences, revisit when | past tense for what was measured, present for the decision |
| Reference | exact lists: commands, options, keys, values | tables |
| Development | how to work on appjail | |

Every concept page has the same headings: **What it is**, **Why it matters**, **How appjail uses it**, **Connections**,
**Limits**, **References**. A new grant, mechanism or external tool needs its concept page, or a section in one, in
the same change as the code.

## Terminology

One term per idea, used everywhere. Current inconsistencies in brackets.

| Term | Meaning | Avoid / current variants |
|---|---|---|
| **jail** | a bubblewrap sandbox started by appjail | "sandbox" is fine in prose for newcomers, once, then "jail" (README mixes both) |
| **app jail** / **helper jail** | the jail an app runs in / a jail for one step (download, extraction, git, icon, proxy, audio daemons) | "network-only jail" = the download helper jail; keep that name for it only |
| **grant** (noun and verb) / **permission** | permission = the manifest key; grant = what the user gives | keep both, defined once |
| **evidence tier** | 1-5 | not "trust tier" |
| **source** | where an app comes from (`kind:target`) | also used for **index source**: say "index source" for catalogs |
| **catalog** / **index** | catalog = one JSON document; index = the local set of sources and their snapshots | used loosely |
| **candidate** | a release not yet installed that `update` found | |
| **quarantine** | the delay before a candidate may be installed | |
| **pin** | the recorded hash, owner id, version and channel | "pinned" is also a channel value; say "pinned channel" for that |
| **registry rule** | the Wayland check on the app's socket | DECISIONS uses "rule A" in tools |
| **confined service** | a D-Bus name with `--call` rules | |
| **private graph** | the per-app PipeWire instance | "private audio graph" |

## References

Cite primary sources only: specifications, manual pages, kernel documentation, upstream project documentation, and
advisories or measurements where they motivated a choice. Open every link before citing it, and re-check the
references at each minor release.

- AppImage: AppImage specification (github.com/AppImage/AppImageSpec); squashfs-tools `unsquashfs(1)`; DwarFS documentation.
- Namespaces: `namespaces(7)`, `user_namespaces(7)`, `pid_namespaces(7)`, `network_namespaces(7)`; Ubuntu's notes on
  restricted unprivileged user namespaces (AppArmor).
- bubblewrap: project README and `bwrap(1)`; CVE-2024-42472 advisory (Flatpak, `--bind-fd`).
- seccomp: kernel `Documentation/userspace-api/seccomp_filter.rst`, `seccomp(2)`; Flatpak's seccomp rules for comparison;
  TIOCSTI history.
- Landlock: kernel `Documentation/userspace-api/landlock.rst`, `landlock(7)`, landlock.io.
- D-Bus: D-Bus Specification (freedesktop.org), D-Bus tutorial; `xdg-dbus-proxy(1)`; Flatpak sandbox permissions doc.
- Portals: XDG Desktop Portal documentation (flatpak.github.io/xdg-desktop-portal), document portal, permission store.
- Wayland: Wayland protocol documentation (wayland.freedesktop.org), wayland-protocols (security-context-v1, ext and wlr
  protocols), wayland.app protocol explorer.
- X11/Xwayland: X.Org security notes on X11 clients; `Xwayland(1)`.
- Audio: PipeWire documentation (pulse-tunnel module, pipewire-pulse, access control); PulseAudio module documentation.
- Devices: kernel DRM documentation (render nodes); V4L2 API (`VIDIOC_QUERYCAP`).
- Network: passt/pasta documentation (passt.top), `pasta(1)`.
- Supply chain: SLSA (slsa.dev), Sigstore documentation, GitHub artifact attestations documentation, GitHub REST
  releases API (asset `digest`).
- Untrusted text: ECMA-48 (control functions); terminal escape injection write-ups; CWE-150, CWE-22, CWE-59.
- Desktop: freedesktop Desktop Entry Specification, Icon Theme Specification, Shared MIME-info; PNG specification (W3C).

## Consistency decisions

Decided with the maintainer before writing:
1. **Tier name**: "evidence tier" everywhere ("trust tiers" in DESIGN goes).
2. **Principles**: P6 (nothing is granted by default) and P7 (the user decides, with the facts in front of them) join
   the principle list.
3. **Downloads without pasta**: the documentation describes the fallback (helper jails on the host network, one warning
   per command), and the installation instructions list `passt` as a dependency to install, not an optional extra.
   The behaviour does not change.
4. The smaller fixes are made while writing: DESIGN no longer points users to `CLAUDE.md`; the GPU grant is described
   with everything it binds (`/dev/dri`, `/dev/nvidia*`, `/sys/dev/char`, `/sys/devices`, Vulkan and GLVND data); the
   namespaces page names every namespace the jail unshares; the compositor assessment is in the present tense.
5. Developer knowledge that is only in `CLAUDE.md` (code layout, VM, CI) moves to the developer guide.

## Site outline

```
Home
Getting started            requirements, install, first app
Understanding appjail
  The problem              threat model and limits
  Principles               P1-P7, each linked to its concepts and decisions
  Acquisition              AppImage format · sources and the resolver · hashes and evidence tiers · attestations ·
                           jailed download and extraction · untrusted text · manifests
  Isolation                namespaces · bubblewrap · the filesystem view · seccomp · Landlock · process lifetime
  Desktop access           Wayland · X11 and the private Xwayland · D-Bus and its proxy · portals · audio · GPU and
                           camera · network · menu entries and opening files
  Updates                  channels · quarantine · blocks and cautions · URL apps · history
  Catalog                  catalogs, index sources, appjail-db, search
Guide                      task pages: installing apps, permissions, files and folders, display, audio and devices,
                           network, D-Bus and portals, menu entry, updates, searching, graphical interface,
                           compositors, troubleshooting
Decisions                  how decisions are recorded, then one group per topic above plus Project, one page per
                           decision
Reference                  commands and options · manifest · permissions · evidence tiers · catalog format · output ·
                           files and environment
Development                architecture · testing in the guests · CI and releases · contributing · assessing a
                           compositor · writing the documentation
Security                   reporting and scope
```
Every concept page: What it is · Why it matters · How appjail uses it · Connections · Limits · References.
