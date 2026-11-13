# Updates

Installing an app is one decision; every update is another. A new release can come from a compromised account, carry
different evidence from the one you trusted, or be swapped after you first saw it. This part explains how `appjail
update` turns each new version into a decision you take with the facts in front of you, and only after the rest of the
world has had time to look at it.

## What an update does

For each installed app, in name order:

1. **Find the candidate.** For a GitHub app, the repository's latest release (by its channel) and the file the app's
   `asset_pattern` selects; for a URL app, a cheap check of whether the file changed; for a file app, the new file you
   give.
2. **Compare.** If GitHub's digest equals the pin (or, without a digest, the same tag and publication time), the app is
   *up to date*. A release published before the installed one is reported and never installed.
3. **Look for blocks.** An owner change or weaker evidence stops the update, whatever you answer.
4. **Quarantine.** A candidate must have been seen for a period (seven days by default) before it can be installed.
5. **Show and ask.** The old and new version, hash, evidence tier and release link, and the permissions it keeps.
6. **Install.** Download in the jail, the same checks as `add`, extraction into a staging area, then the swap.
7. **Record.** The new manifest is committed to the history.

Each app ends in one result: *current*, *waiting* (in quarantine; run `update` again later), *blocked*, *declined*,
*pinned* (it follows no releases), *updated* or *failed*. With several apps a table repeats them, and the exit status is
1 if any was blocked, failed, or not checked because the GitHub rate limit was reached.

## The pages

1. **[Channels and quarantine](quarantine.md)**: which releases an app follows, and why a new one waits.
2. **[What blocks an update](blocks.md)**: the findings that stop an update, and those that are only shown.
3. **[URL and file apps](url-and-file.md)**: how a file with no release behind it is checked and replaced.
4. **[History and rollback](history.md)**: how an update replaces a version safely, and the record of what changed.

The decisions behind this part are in [Decisions: updates](../../decisions/updates/index.md).
