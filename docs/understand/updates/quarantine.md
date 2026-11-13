# Channels and quarantine

*Part of [Updates](index.md). Next: [what blocks an update](blocks.md).*

## What it is

A **channel** says which releases of a GitHub app `update` considers: `stable` (the latest release that is not a
pre-release), `prerelease` (pre-releases too) or `pinned` (none: the app stays at the version installed with `--tag`).

A **quarantine** is a delay between the moment a new version is first seen and the moment it may be installed.

## Why it matters

Compromised releases are usually noticed: by the publisher, who sees a release they did not make; by users of the
project; by the scanners of package ecosystems and security researchers. That takes time, often days. An updater that
installs every release the moment it appears gives that time to the attacker; one that waits lets the rest of the world
find the problem first. The same delay makes a quietly swapped asset visible: the version you would install is the one
that has been public, unchanged, for the whole period.

## How appjail uses it

- **Channels.** `add` writes `stable`, or `prerelease` with `--prerelease`, or `pinned` with `--tag`. `update APP
  --channel stable|prerelease|pinned` changes and saves it; `update --prerelease` considers pre-releases for one run.
  A pinned app is never updated.
- **The clock.** A candidate is identified by GitHub's digest of the asset, or, when there is none, by its tag,
  publication time and size. The first time `update` sees it, it records the time in the app's `pending.json`. The
  candidate can be installed once that time plus the quarantine has passed: seven days by default, `--quarantine DAYS`
  for one run (with a warning below seven; 0 disables it). A different candidate starts a new clock, including a
  different asset in the same release when GitHub gives a digest.
- **The tier 4 hash.** Without a digest nothing identifies the content, so the first run that sees a candidate offers to
  download it once, in the download jail, only to hash it. When the quarantine ends, the download that would be
  installed must hash the same; if it does not, nothing is installed ("changed during quarantine"), the clock starts
  again and the new hash is recorded.
- **Nothing to do while waiting.** A waiting candidate needs no action: run `update` again later.

## Connections

- The evidence the candidate carries is checked before the clock matters: [what blocks an update](blocks.md),
  [hashes and evidence tiers](../acquisition/evidence.md).
- URL apps keep their candidate on disk during the quarantine: [URL and file apps](url-and-file.md).
- Decision: [A new version waits in quarantine](../../decisions/updates/quarantine.md).

## Limits

- Security fixes wait too; `--quarantine 0` installs at once when you decide a fix is worth it.
- Declining the tier 4 hash download skips that check (with a warning); an asset swapped in place without a new
  publication time is then not seen.
- A quarantine helps against compromises that are found; it does nothing against a publisher who is malicious from the
  start. Containment is for that.

## References

- SLSA, [Supply chain threats](https://slsa.dev/spec/v1.0/threats-overview): compromised builds and releases.
- NIST NVD, [CVE-2024-3094](https://nvd.nist.gov/vuln/detail/CVE-2024-3094): the backdoor in xz releases, found
  weeks after they were published, an example of a compromise the wider community eventually notices.
