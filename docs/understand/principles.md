# Principles

Seven rules answer [the problem](problem.md). They are the test every feature has to pass: a change that breaks one
of them is a change of design, not of implementation. Each rule below says what it answers, what it means in practice,
and where it is put into practice.

## 1. Nothing from the network is executed

**Rule.** An app is described by a declarative manifest: its source, its pinned hash, its permissions. No shell
script, configuration code or program text that comes from the network is ever sourced, evaluated or executed by
appjail, and catalogs of applications are parsed as data.

**Answers.** Install scripts are code written by someone else and run with your privileges, usually outside any
sandbox; one compromised script, or one compromised repository of scripts, reaches every user. A manifest that can
only say *what* to install cannot be made to *do* anything.

**In practice.** The manifest is a TOML file with a strict schema: an unknown key or a wrong type makes it invalid.
Text from the network (release names, catalog entries, the AppImage's own menu entry) is cleaned of terminal escape
sequences before it is shown and never reaches a shell. The app's own code runs only inside its jail; so does the
AppImage's built-in extractor, when appjail falls back to it.

## 2. appjail does not update itself

**Rule.** appjail is updated by you, through your package tool or a reviewed `git pull`. It never fetches code to run,
including newer versions of itself.

**Answers.** A tool that updates itself from the network is a single point through which every installation can be
compromised at once.

**In practice.** The helper binaries appjail cannot take from the distribution (the GitHub CLI used to verify
attestations, the DwarFS extractor) are pinned in appjail's source by URL, size and hash. They are installed only when
you ask, checked before every use, and moved to a newer version only by a change to appjail's source.

## 3. You name the one source

**Rule.** An app comes from the source you give: a GitHub `owner/repo`, an https URL, or a file. Nothing else may
choose or change it, including the update information that an AppImage may carry inside itself.

**Answers.** Software that tells its installer where to fetch its next version can redirect itself; a catalog that
names a repository can name the wrong one. The decision of where code comes from is yours, and stays visible in the
manifest.

**In practice.** The manifest records the source with its kind (`github:`, `url:`, `file:`). For GitHub, the numeric id
of the account that owns the repository is recorded too, and an update from a repository now owned by another account
is blocked. A catalog search only suggests the command to type.

## 4. Containment is the backstop

**Rule.** Every step that handles untrusted bytes runs in a jail with only the access that step needs: downloads in a
jail with a network and no file of yours, extraction in a jail with neither network nor anything outside its work
directory, apps in a jail with only what their manifest grants. Every permission the manifest can express is
enforced; what appjail cannot enforce, it refuses, and never ignores.

**Answers.** Provenance can fail: a publisher can be malicious, an account can be taken over between two checks. When
it fails, the damage must be limited to what was granted.

**In practice.** A grant that cannot be honoured stops the app with a message instead of starting it with less
protection than promised: `network` without the `pasta` tool, `network_host` without Landlock, a Wayland socket that
offers screen capture to an app without `full_wayland`. When the private audio graph cannot start, an app without
the `mic` permission gets no sound rather than the host's audio socket, which would also open the microphone. Where a missing
helper only weakens a *helper* jail, appjail says so and goes on: without `pasta` the download jails share the host
network, with a warning on every command that does it (install `passt` to avoid it). One permission knowingly gives
more than its name: `audio_mode = pulse` hands the app the host's Pulse socket, which always includes the microphone.
You choose that mode, and `add` and `perms` say so when you do; the default mode keeps the promise.

## 5. Evidence is explicit and never silently lowered

**Rule.** Every app carries an *evidence tier* that says what is known about who built its bytes, from a verified build
attestation (tier 1) down to "first seen" (tier 5). An update that would lower it is blocked. A new version is a
reviewed difference, held in quarantine before it can be installed.

**Answers.** A compromised publisher often removes what would give it away: a release without an attestation, an asset
without the digest the old ones had. A quarantine gives the publisher, the community and scanners time to notice a
compromised release before it reaches you.

**In practice.** `update` shows the old and the new hash, tier and release before asking; it refuses an owner change
or a lower tier whatever you answer; it waits seven days by default after first seeing a candidate. For a release that
has no publisher digest, `update` offers to hash the candidate when it first sees it, and then refuses to install it
unless it still hashes the same when the quarantine ends.

## 6. Nothing is granted by default

**Rule.** A new app gets a private home, a read-only view of the system and a window. Sound, microphone, GPU, camera,
network, folders, D-Bus names and portals are permissions you grant one by one, and can read back and take back.

**Answers.** A sandbox that starts permissive is mostly a sandbox in name: tools that share audio, the session bus,
the network and the display sockets by default leave an app most of what it could do unconfined. A missing grant
fails visibly and is cheap to fix; an unneeded grant fails silently, for example as an open microphone.

**In practice.** `add` grants only the window, and an app with no window at all can be given `display = none`. The
risky grants are announced with a warning when you give them. A few grants are never
possible, whatever you ask: the whole home directory, credential stores, the D-Bus names that control the desktop.

## 7. You decide, with the facts in front of you

**Rule.** Every change that decides which bytes run or what an app may reach (installing, updating, granting,
replacing a catalog, removing) is shown before it is made and needs your agreement; the default answer is No. A warning
is not consent.

**Answers.** Security decisions taken by a tool on the user's behalf go stale, and decisions taken by a user without
the facts are guesses. A message that scrolls past in a terminal, or never shows when an app is started from a menu,
cannot stand in for a decision.

**In practice.** `add` shows the repository's owner, account age and popularity before anything is downloaded;
`update` shows the difference; `perms` shows the permissions before and after. Where a risk can only be accepted, it
is a permission recorded in the manifest (such as `full_wayland`), not a warning printed at every start. The graphical
interface runs the same commands and asks the same questions; it never answers them for you.

A few commands act at once because they do exactly what you typed and change nothing an app may do: `update --channel`
saves the new channel, `update --pattern` the new file pattern (the file it selects is still reviewed and quarantined), `desktop --remove` and `--prune` delete appjail's own menu entries, and `index rollback` swaps
back a catalog (and can be swapped again). `desktop NAME` asks with Yes as the default, since you just asked for the
entry. `remove`, `perms`, `portals` and `desktop` accept `--yes` for scripts.

## How the principles fit together

Principles 1 to 3 keep the *decision* of what to run with you and out of the reach of the software and its metadata.
Principle 5 makes that decision durable: once taken, it can only be changed visibly. Principles 4 and 6 limit the
cost of a wrong decision. Principle 7 is what makes the decisions yours.
