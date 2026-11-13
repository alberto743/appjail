# How decisions are recorded

The pages under "Understanding appjail" explain how appjail works. These pages explain why it works that way rather
than another: what the problem was, which options were considered, what was chosen, what it costs, and when the
choice should be looked at again. A decision that has no "revisit when" is one that follows directly from a
[principle](../understand/principles.md); changing it means changing the principle.

Each decision is written as:

- **Context**: the problem, and the facts it rests on (measured where possible, with the versions measured).
- **Options**: what was considered.
- **Decision**: what was chosen.
- **Consequences**: what it costs, and what it does not cover.
- **Revisit when**: the condition that would reopen it.

The decisions are grouped by topic, the same topics as the explanations under "Understanding appjail", plus one for
the project itself:

| Topic | Covers |
|---|---|
| [Acquisition](acquisition/index.md) | sources, owner pinning, evidence tiers, attestations, pinned tools |
| [Isolation](isolation/index.md) | bubblewrap, extraction, default grants, granted paths, seccomp, Landlock, process lifetime |
| [Desktop access](desktop/index.md) | Wayland, Xwayland, D-Bus, portals, audio, camera, network, menu entries, icons |
| [Updates](updates/index.md) | quarantine, blocks, URL apps, manifest history |
| [Catalog](catalog/index.md) | appjail-db, the catalog format |
| [Project](project/index.md) | supported systems, the window, output, security reports, releases and CI, related projects |

Deferred features and rejected tools are recorded in the group they belong to. When a decision changes, its page is
updated in the same change as the code, and the old reasoning stays in the project's history.
