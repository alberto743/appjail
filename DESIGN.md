# appjail: design

The design of appjail is documented on its site, <https://alberto743.github.io/appjail/>, from the Markdown under
[`docs/`](docs/). This file only says where each part is.

| Part | Where |
|---|---|
| Principles | [`docs/understand/principles.md`](docs/understand/principles.md) |
| Threat model and limits | [`docs/understand/problem.md`](docs/understand/problem.md) |
| Getting an app: format, sources, evidence tiers, attestations, jailed download and extraction, untrusted text, the manifest | [`docs/understand/acquisition/`](docs/understand/acquisition/) |
| The jail: namespaces, bubblewrap, the filesystem view and grants, seccomp, Landlock, process lifetime | [`docs/understand/isolation/`](docs/understand/isolation/) |
| The desktop: Wayland, Xwayland, D-Bus, portals, audio, GPU and camera, network, menu entries | [`docs/understand/desktop/`](docs/understand/desktop/) |
| Updates: channels, quarantine, blocks, URL and file apps, history | [`docs/understand/updates/`](docs/understand/updates/) |
| Catalogs and search | [`docs/understand/catalog/`](docs/understand/catalog/) |
| Commands, manifest schema, permissions, catalog format, output, files and environment, policy lists | [`docs/reference/`](docs/reference/) |
| Code layout and walk-throughs | [`docs/develop/architecture.md`](docs/develop/architecture.md), [`docs/develop/source-tour.md`](docs/develop/source-tour.md) |

Why each choice was made, what was rejected and what is deferred: [DECISIONS.md](DECISIONS.md).
