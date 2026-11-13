# Owner changes and weaker evidence block

*Decision on [updates](index.md).*

**Context.** A compromised publisher often removes what would reveal it: a release without the attestation the previous
ones had, an asset without a digest. A repository that changed owner may be in someone else's hands. A prompt that
offers to go on anyway turns those signals into one more question to answer "yes" to.

**Decision.** Two findings **block** an update, with no option to override and nothing downloaded or recorded: the
repository's owner account id differs from the pinned one, or the evidence tier would be lower than the installed one
(the digest is gone, or an app at tier 1 has a release without an attestation). To go on, the app is removed and added
again after checking the repository, which makes the new trust decision explicit. Other findings are **cautions**,
shown but not blocking: no owner pinned yet, a renamed or transferred repository (the new name is recorded), an archived
repository.

**Consequences.** A project that legitimately moves to another account, or stops publishing attestations, needs a
`remove` and `add`, which also deletes the app's private home. Permissions are never changed by an update.
