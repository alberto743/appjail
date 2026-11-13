# What blocks an update

*Part of [Updates](index.md). Previous: [channels and quarantine](quarantine.md). Next: [URL and file apps](url-and-file.md).*

## What it is

Some findings during an update are **blocks**: the update stops, nothing is downloaded or recorded, and no answer or
option lets it go on. Others are **cautions**: shown prominently, but you decide.

## Why it matters

The signs of a compromised publisher are often removals: a release without the attestation the previous ones had, an
asset without a digest, a repository now owned by another account. A prompt that offers to continue anyway turns each
of these into one more "yes" to type through. Making them blocks means the only way forward is a fresh, explicit trust
decision: removing the app and adding it again, with the review of `add`.

## How appjail uses it

| Finding | Effect |
|---|---|
| the repository's owner account id differs from the pinned one | **block**: the name now belongs to someone else |
| an app at tier 1 meets a release without an attestation on GitHub | **block**, before any download |
| an app at tier 1 meets an attestation that does not verify | **block**, after the download; nothing is installed |
| GitHub no longer gives a digest for the asset of a tier 3 app | **block**: tier 3 would become 4 |
| a tier 4 candidate hashes differently at the end of the quarantine | **block**; the clock restarts |
| a URL or file app at tier 4 changes without a matching `--sha256` | **block**, with the hint to pass it |
| no owner id pinned yet (an app added before owner pinning) | caution; pinned once you approve |
| the repository was renamed or transferred (same account) | caution; the new name is recorded |
| the repository is archived | caution |

An update never changes permissions: the new manifest keeps the old one's grants.

## Connections

- The tiers and the owner id come from installation: [hashes and evidence tiers](../acquisition/evidence.md),
  [sources and the resolver](../acquisition/sources.md).
- Decisions: [Owner changes and weaker evidence block](../../decisions/updates/blocks.md),
  [The owner account is pinned](../../decisions/acquisition/owner-pinning.md).

## Limits

- A project that moves to another account on purpose, or stops attesting its releases, needs a `remove` and `add`,
  which also deletes the app's private home.
