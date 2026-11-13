# A new version waits in quarantine

*Decision on [updates](index.md).*

**Context.** When a publisher's account or build is compromised, the malicious release is usually noticed within days:
by the publisher, by users of the project, by scanners. Installing every release the moment it appears gives that
window to the attacker.

**Decision.** `update` installs a release only after it has been seen for a quarantine period: seven days by default,
set per run with `--quarantine DAYS` (a warning below seven; 0 turns it off). A candidate is identified by GitHub's
digest of the asset, or, when there is none, by its tag, publication time and size; the first time it is seen is kept
in the app's `pending.json`. A different candidate, including a swapped asset in the same release when GitHub gives a
digest, starts a new clock. A release published *before* the installed one is never installed, only reported.

**Tier 4.** Without a digest nothing identifies the content, so the first check that sees a candidate asks to download
it once, in the download jail, only to hash it. When the quarantine ends, the download that would be installed must hash
the same; otherwise nothing is installed ("changed during quarantine"), the clock restarts and the new hash is recorded.

**Consequences.** Security fixes also wait; `--quarantine 0` installs at once when the user decides that a fix is worth
it. Without the tier 4 download, an asset swapped in place without a new publication time is not seen. Apps added from
a file have no quarantine: you hold the bytes.
