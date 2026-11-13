# Searching

```sh
appjail index update            # once, and whenever you want a fresh catalog
appjail search editor           # the best 20 matches
appjail search pdf viewer --all
```

A hit shows the app's name, description and source, and the `appjail add` command for it. It is a suggestion: check
the repository before installing, as `add` will ask you to.

`search` needs a catalog first: `appjail index update` downloads the built-in one (from appjail-db, rebuilt weekly from
the AM list and the AppImageHub feed), shows what changed since the last one, and asks before replacing it. Apps listed
on GitLab, Codeberg or Forgejo are shown for information; install them with `--url` if they publish an AppImage file.

## More catalogs

```sh
appjail index add mine --url https://example.org/apps.json
appjail index add local --file ~/apps.json
appjail index update mine
appjail index status            # sources, revisions, update times
appjail index rollback mine     # back to the previous catalog of a source
appjail index remove mine
```

With several sources, each hit shows its source in brackets. A catalog is a JSON file in the
[catalog format](../reference/catalog-format.md); how catalogs are checked is explained in
[Catalog](../understand/catalog/index.md).

`search --json` and `index status --json` print JSON for scripts.
