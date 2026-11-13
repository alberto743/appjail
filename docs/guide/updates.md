# Updates

```sh
appjail update              # every installed app
appjail update lagrange     # one app
```

For each app, `update` finds the newest release it follows, compares it with what is installed, and prints one result:

| Result | Meaning | What to do |
|---|---|---|
| current | nothing newer | nothing |
| waiting | a new release was seen and is in quarantine | run `update` again after the date shown |
| updated | you agreed and it was installed | nothing |
| declined | you answered no | nothing |
| blocked | the owner changed, the evidence got weaker, or the content changed during the quarantine | read the message; see below |
| pinned | the app follows no releases | `update APP --channel stable` to follow them |
| failed | an error; the message says which | fix the cause and run again |
| not checked | the GitHub rate limit was reached | set `GITHUB_TOKEN`, or wait an hour |

Before installing, `update` shows the old and new version, hash and evidence tier, and the release link, and asks.
Permissions never change in an update. Why a release waits and what blocks one is explained in
[Updates](../understand/updates/index.md).

## Options

| Option | Effect |
|---|---|
| `--quarantine DAYS` | the waiting period for this run (default 7; 0 installs at once, for an urgent fix) |
| `--prerelease` | consider pre-releases this time |
| `--channel stable\|prerelease\|pinned` | what the app follows from now on |
| `--sha256 HEX` | for a URL or file app: the publisher's hash of the new version (keeps or earns tier 4) |
| `--file PATH` | for an app added from a file: replace it with this AppImage |
| `--verify` | for a URL app: download again at the end of the quarantine and compare |
| `--pattern GLOB` | for a GitHub app: which file of a release it follows, when the publisher renamed its files |
| `--allow-private-redirects` | for a URL app: let the download be redirected to a machine of your local network |

## When an update is blocked

A block cannot be overridden. For an owner change, check the repository on GitHub: if the project really moved, remove
the app and add it again, which makes a new trust decision (and deletes the app's private home: back it up first from
`~/.local/share/appjail/apps/NAME/home`). For weaker evidence, find out why the new release lacks the digest or the
attestation the old ones had before deciding the same way.

## When the release file was renamed

appjail picks the file of each release with a pattern made from the first one (`App-*-x86_64.AppImage`). If a
publisher renames its files, `update` stops with `no asset in TAG matches 'PATTERN'` and lists the files of the release.
Choose the right one and give a pattern for it:

```sh
appjail update NAME --pattern 'App-*-linux-x64.AppImage'
```

The pattern is saved once it selects a file of the latest release; the new file then goes through the usual review and
quarantine.

## History

`appjail history` lists every change appjail made to the manifests; `appjail history APP` those of one app. `run` warns
when a manifest was changed outside appjail.
