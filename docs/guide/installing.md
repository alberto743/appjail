# Installing apps

## From a GitHub release

```sh
appjail add owner/repo
```

Before anything is downloaded, `add` shows:

- the repository, its description, and its owner: the name, the numeric account id, and how old the account is;
- the number of stars, and warnings for a fork, an archived or renamed repository, a young account or very few stars;
- the release and the AppImage chosen from it, GitHub's digest of the file, and whether a build attestation exists;
- the permissions the app will get.

Check the owner before answering: a lookalike repository rarely has an old account and an established project behind it.

| Option | Effect |
|---|---|
| `--tag TAG` | a specific release instead of the latest; the app is then pinned and `update` leaves it alone |
| `--prerelease` | follow pre-releases |
| `--name NAME` | the app's local name (default: the repository's) |
| `--allow`, `--dir`, `--dbus`, `--portal`, `--display`, ... | permissions at install time ([Permissions](permissions.md)) |
| `--desktop` | also create a menu entry ([Menu entry](menu-entry.md)) |

If several files of the release fit (for example two flavours of the app), you choose. If `unsquashfs` is not
installed, `add` offers to use the AppImage's own extractor inside a jail with no network; installing `squashfs-tools`
avoids the question.

## From a file or a URL

```sh
appjail add --file ~/Downloads/Tool-x86_64.AppImage [--name tool] [--sha256 HEX]
appjail add --url https://example.org/dl/Tool-x86_64.AppImage [--name tool] [--sha256 HEX] [--max-size MIB]
```

Nothing identifies who published such a file, so the app is at evidence tier 5; give the hash the publisher lists with
`--sha256` and it is tier 4 (a mismatch aborts). A URL must be https; it is downloaded in a jail, at most 1 GiB unless
`--max-size` (up to 2 GiB, the limit for any AppImage); a redirect through plain http needs an extra confirmation
unless the hash matches. A redirect to a machine of your local network is refused, unless your URL is itself on your network or you pass
`--allow-private-redirects` ([why](../decisions/acquisition/private-redirects.md)). A file is copied and
the copy is checked; the original is untouched.

## Helper tools

Two kinds of AppImage need a helper appjail does not take from your distribution:

```sh
appjail tools install dwarfs    # AppImages built on DwarFS instead of SquashFS
appjail tools install gh        # verifying build attestations (evidence tier 1)
appjail tools status
```

Each is pinned in appjail's source by URL, size and hash, downloaded in a jail, and checked before every use.

## Evidence tiers

`appjail list` shows each app's tier: 1 a verified build attestation, 3 GitHub's digest matched, 4 trust on first use
(or your `--sha256` matched), 5 the bytes alone. What each proves is explained in
[hashes and evidence tiers](../understand/acquisition/evidence.md).
