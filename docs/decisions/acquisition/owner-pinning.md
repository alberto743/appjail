# The owner account is pinned

*Decision on [acquisition](index.md).*

**Context.** A GitHub repository is named `owner/repo`, and the name can change hands: an account deleted and its name
registered again by someone else, or a repository transferred. A name that resolves to a different account looks the
same in every URL.

**Decision.** `add` records the numeric id of the account that owns the repository (`owner_id`), which GitHub never
reuses. `update` compares it with the current owner's id and blocks when it differs, whatever the user answers; to go
on, the app must be removed and added again after checking the repository. A rename or transfer that keeps the same
account, and an archived repository, are shown as cautions, not blocks.

**Consequences.** One more API request per check. A project that moves to a new organisation on purpose needs a
`remove` and `add`, which also deletes the app's private home. Manifests written before owner pinning get a warning,
and the id is pinned once the user approves an update.
