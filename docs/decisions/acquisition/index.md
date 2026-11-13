# Acquisition

Decisions about getting an app: where it may come from, how its bytes are checked, and what evidence is kept about
who built them. How it works is explained in [Acquisition](../../understand/acquisition/index.md).

| Decision | Covers |
|---|---|
| [You name the source; releases from GitHub only](sources.md) | sources, AppImage update information, other forges |
| [The owner account is pinned](owner-pinning.md) | repositories deleted and registered again under the same name |
| [Evidence tiers, without a GPG tier](evidence-tiers.md) | what each tier proves, and why tier 2 is not implemented |
| [Attestations verified with a pinned `gh`](attestations.md) | Sigstore build attestations, and what their identity covers |
| [Helper tools pinned in the source](pinned-tools.md) | `gh` and DwarFS, and how they are updated |
