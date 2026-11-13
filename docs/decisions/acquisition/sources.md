# You name the source; releases from GitHub only

*Decision on [acquisition](index.md).*

**Context.** An AppImage can carry update information that tells an updater where to fetch its next version, and a
catalog can name a repository for an app. Either would let data from the software, or from a third party, decide
where code comes from. Of the apps the AM project lists, about 95% are GitHub releases.

**Options.** Follow the embedded update information (as AppImageUpdate does); take sources from a catalog; let the
user name the source, once, and record it.

**Decision.** The user names the one source: `owner/repo` on GitHub, an https URL, or a local file. It is recorded in
the manifest with its kind (`github:`, `url:`, `file:`) and nothing else can change it; the update information inside
an AppImage is ignored, and a catalog only suggests the command to type. Releases are resolved on GitHub only.

**Consequences.** Apps released on GitLab, Codeberg, Forgejo or a vendor's site can be installed with `--url` or
`--file`, but nothing then identifies their publisher (tier 5, or tier 4 with a hash the user gives). The catalog
already records such sources; `search` shows them as information. Those forges publish release assets with sizes but
not GitHub's per-asset digest or attestations, so a resolver for them would reach tier 4 at best.

**Revisit when** a wanted app is released only on another forge. A resolver would sit behind the same interface as the
GitHub one (repository information, latest release, assets with size and optional digest).
