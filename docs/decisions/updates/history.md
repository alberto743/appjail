# A local history of the manifests

*Decision on [updates](index.md).*

**Context.** The manifests hold the pins (hash, owner, tier) and sit in your configuration directory, where any process
of yours can write. A change made outside appjail would go unnoticed.

**Decision.** Every change appjail makes to its configuration (`add`, `update`, `perms`, `remove`, a new channel or tier)
is committed to a local git repository there, by `git` running in a jail with no network that sees only that
directory, with your git configuration, hooks and signing ignored. `run` warns when an app's manifest differs from its
last commit, and `appjail history` lists the changes. It is best effort: without `git`, or when the directory is already
inside another repository (a dotfiles repository), there is no history and no error. Nothing is ever pushed.

**Consequences.** It detects edits made behind appjail's back; it does not stop a process that also rewrites the
repository. It is evidence, not prevention.
