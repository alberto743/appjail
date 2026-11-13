# Reading the source

A guided tour for someone about to change appjail. [Architecture](architecture.md) maps every concept onto modules;
this page follows the code itself: where a command starts, what it calls in which order, where state is kept, and how
to add something without breaking the rules the rest of the code relies on. Function names are given as
`module.function`; all modules are under `src/appjail/`.

## Rules the code relies on

Five conventions hold everywhere. Knowing them makes most modules easy to read, and a change that breaks one is
almost certainly wrong.

| Rule | Where it lives | What it means for a change |
|---|---|---|
| **Standard library only** | `pyproject.toml` has no dependencies | no imports from PyPI, in the package or in the window |
| **Untrusted work happens in a jail** | `jail.py` (helper jails), `runtimejail.py` (the app jail) | a new step that touches downloaded bytes or runs a helper program gets a jail built from `jail.common_args`, never a plain `subprocess` call |
| **Policy is pure** | `grants.py`, `valid.py`, `manifest.py`, `updater.blocks` | decisions about what is allowed take values and return reasons; they do no I/O, so they are easy to test exhaustively |
| **Every line printed goes through the console** | `console.Console`, `textsafe.clean` | commands never call `print`; untrusted text cannot reach the terminal unfiltered |
| **Every write is atomic, every temporary directory is cleaned up** | `store.atomic_write`, `store.staging`, `store.remove_tree` | no `open(path, "w")` on a file appjail keeps; staging goes in a `with store.staging()` block |

## From the command line to a command

```
__main__.py  →  cli.main(argv)  →  cli.build_parser()  →  COMMANDS[name](args, client, console, app_args)  →  cmd_*.py
```

- `cli.main` splits off everything after `--` (it belongs to the app), parses the rest, creates the `Console`, and
  routes the warnings of the jail layer to it (`jail.warn_with`).
- `cli.COMMANDS` maps each command to a small handler that calls the real function in a `cmd_*.py` module. `cli.py`
  holds no command logic.
- Errors are exceptions, turned into exit codes in one place:

| Exception | Raised for | Exit status |
|---|---|---|
| `console.Abort` | the user declined, or the command cannot go on (message shown as is) | 1 |
| `errors.JailError` | a helper jail failed or was refused | 1 |
| `errors.RunError` | an app cannot be started as asked | 1 |
| `valid.ManifestError` | a malformed manifest or a refused value | 1 |
| `github.GitHubError`, `catalog.IndexProblem`, `OSError` | network, catalog and file errors | 1 |
| `KeyboardInterrupt` | Ctrl-C | 130 |
| argument errors (argparse) | a usage error | 2 |

## Walk-through: `appjail add owner/repo`

`cmd_add.cmd_add`, top to bottom. Every network access and download comes after every check that can be made without
it.

1. `install.new_app_name`: the name, which must be free.
2. `permargs.permissions_from_args`: every permission option is validated now (paths exist and are allowed, D-Bus names
   and portals are permitted), before any network access. `permargs.require_network_isolation` refuses `network`
   without `pasta` and `network_host` without Landlock.
3. `github.Client.repo_info`, then `cmd_add.show_review`: the repository and its owner.
4. `cmd_add.choose_release_asset` (`github.appimage_candidates`, `install.choose_asset`) and
   `cmd_add.show_asset_evidence`: the release, the file, its digest, whether an attestation exists.
5. `permargs.show_permissions`: what the app will be granted, with warnings.
6. `install.ask_extractor`: if `unsquashfs` is missing, whether to accept the AppImage's own extractor.
7. `console.confirm`: nothing has been downloaded yet.
8. Inside `with store.staging() as stage`:
    - `install.download_verified` → `Services.download` (`jail.download`): `fetcher.py` in the download jail, then the
      size, the SHA-256 against the digest and the AppImage type, on appjail's side;
    - `install.gather_evidence` → `Services.verify` (`attest.verify`): tier 1 if an attestation verifies;
    - a `manifest.Manifest` is built and checked (`install.check_record`);
    - `install.swap_in` → `Services.extract` (`appimage.extract`): extraction in its jail, then the tree, the markers
      (`root.sha256`, `root.tree.sha256`) and the manifest, last. On any failure everything placed is removed again.
9. `install.finish_add`: the report, the history commit (`history.record`) and the optional menu entry.

`add --file` and `add --url` (`cmd_addimage.py`) follow the same steps with `imagesrc.py` instead of the resolver.

## Walk-through: `appjail run NAME`

`runner.launch` is the heart of the app jail. Its order matters: everything that can refuse comes before anything is
started, and everything started is registered on one `contextlib.ExitStack`, so it is stopped in reverse order when the
app ends or a step fails.

1. `runner.prepare`: the manifest; the AppImage must hash to the pin (otherwise `RunError`); the tree is reused only
   if its markers match, else extracted again.
2. `history.modified`: a warning if the manifest was changed outside appjail.
3. `runner._open_grants` → `runtimejail.Grants`: each granted folder and file opened once and checked through its
   descriptor (`grants.sensitive_reason`, `grants.directory_reason`).
4. `network_host` without Landlock is refused (`landlock.available`).
5. Display: `wayland.RestrictedSocket` (a restricted socket when the compositor offers one), then
   `runner._check_wayland_socket` (`wayland.privileged`): the registry rule, before anything else is started.
6. `runner._private_audio` (`audiomode.resolve`, `audiojail.PrivateAudio`): the private audio graph, or the fallback.
7. `runner._seccomp_filter` (`seccomp.program`): the filter, in memory or, behind `pasta`, in a private file; and the
   lifeline (`jail.Lifeline`).
8. `runner._portal_and_bus` (`portal.Instance`, `dbusproxy.check_owners`, `dbusproxy.Proxy`): the portal identity and
   the filtered bus.
9. `runtimejail.runtime_args`: the complete `bwrap` argument list. This is the one place to read to know what an app
   sees.
10. Wrapping: behind `pasta`, `jail.net_wrap` with `reopen.wrap` (the grants opened again in the namespace); otherwise
    `landlock.wrap`.
11. `runner._run_app` and `runner._wait_group`: start, publish the jail's pid to the portal, forward signals to the
    process group, and kill what is left when the app exits.

## Walk-through: `appjail update`

`cmd_update.cmd_update` loops over the apps (`updater.installed`) and calls `cmd_update.update_app` for each, which
dispatches by source kind:

- `github:` → `cmd_update.update_github`: `repo_info` and the latest release, `cmd_update.pick_asset`,
  `cmd_update.is_current`; then `updater.blocks` (owner change, lower tier: stop) and `updater.cautions`;
  `updater.note_seen` and `updater.quarantine_ends` (the quarantine; `cmd_update.hash_candidate` for tier 4);
  `install.show_change`, the confirmation, and `cmd_update.install_release`, which reuses `install.download_verified`,
  `install.gather_evidence` and `install.swap_in`; finally `install.finish_update`.
- `url:` → `cmd_updateimage.update_url` (`jail.check_url`, `fetcher.check`: the conditional and ranged requests).
- `file:` → `cmd_updateimage.update_file`.

An update never changes permissions: the new `Manifest` is built from the old one with the new pins.

## Helper jails

All of them are built in `jail.py` from `jail.common_args` (namespaces, no nested user namespaces, no capabilities, a
cleared environment, the read-only system) plus the few binds of the step, for example `jail.download_args`,
`jail.extract_args`, `jail.local_git_args`. `jail.run` adds the seccomp filter and, for jails with a network,
`jail.net_wrap` (`pasta`); `jail.supervise` runs the command with a timeout, a watch on disk use and capped output. A
new helper jail follows the same pattern: a `*_args` builder that binds only what the step needs, run through
`jail.run`.

## Where state lives

| Path (`store.py`) | Holds |
|---|---|
| `config_dir()/apps/NAME.toml` (`~/.config/appjail`) | the manifests; the directory is the manifest-history git repository |
| `app_dir(NAME)` (`~/.local/share/appjail/apps/NAME`) | `app.AppImage`, the extracted `root/`, the markers `root.sha256` and `root.tree.sha256`, the private `home/`, the generated `etc/`, `pending.json` during a quarantine |
| `tools_dir()` | the pinned helper tools |
| `staging_root()` | temporary directories of `store.staging`, removed when the block ends |
| `data_dir()/index/` | the catalogs (`indexstore.py`) |

`APPJAIL_DATA_DIR` and `APPJAIL_CONFIG_DIR` override the two roots; the tests use them for a private tree per test.

## Testing a change

- **The `Services` seam.** `services.Services` gathers what `add` and `update` do to the outside world (download,
  extraction, attestation check). Tests pass their own, so a whole `add` or `update` runs without a network or a jail.
  The GitHub client is passed in the same way (`helpers.FakeClient`).
- **Fixtures** (`tests/conftest.py`): `h` and `sandbox` give a private data and config tree; `runtime` a fake runtime
  directory with real sockets; `no_history` and `no_portal_store` (automatic) keep tests away from git and the real
  portal store. Shared helpers are in `tests/helpers.py`: scripted consoles (`Script`, `Answers`), fake releases and
  assets, a local URL server, fake compositor registries.
- **Integration tests** start real jails and skip unless `APPJAIL_INTEGRATION=1`, which `tests/vm/test.sh` sets in the
  guest. Opt-in suites that download need `APPJAIL_E2E=1` or `APPJAIL_LIVE=1`.
- **Checks that guard the documentation and the style**: `test_docs.py` (every command and option documented),
  `test_lint.py` (ruff), `test_reuse.py` (licence headers), `test_assessment.py` (the compositor tables).

## Recipes

**A new command.** A `cmd_<name>.py` module with a `cmd_<name>(args, console)` function; its parser entry in
`cli.build_parser` and its handler in `cli.COMMANDS`; a menu or form in the window only if it is useful there
(`gui/argv.py` builds its command line); the command and its options in the guide and the reference.

**A new permission.** Follow an existing one such as `linger` through the code:

1. `manifest.py`: the field in `Permissions` (default denied), its name in `BOOL_PERMS` for a switch (the `--allow` and
   `--deny` choices are taken from it) or in `PERM_KEYS` for another kind of value, the writer (`dumps`), and any
   consistency rule (`_network_consistency` is an example);
2. `permargs.py`: `permissions_from_args`, the summary lines, and a warning in `RISKY_GRANTS` if it widens the jail;
3. its effect, almost always in `runtimejail.runtime_args` or `runner.launch`;
4. the window's argument builder (`gui/argv.py`);
5. tests in `test_manifest.py`, `test_cli_add.py`, `test_runner.py` and `test_gui_argv.py`;
6. the permission reference, the guide, the concept page it belongs to, and a decision page if a choice was made.

**A refused path or D-Bus name.** Add it to the lists in `grants.py` (`SECRET_HOME_DIRS`, `PERSIST_HOME_DIRS`,
`DBUS_BLOCKED`, ...) with a comment saying why, a test in `test_manifest.py` or `test_dbus.py`, and the reason in the
matching decision page.

**A new helper program.** If it runs on untrusted input, it runs in a helper jail (above). If it is not packaged by the
supported distributions, it is pinned in `tools.py` by URL, size and hash, installed only on request.
