# Contributing

## Before you start

- Read [the principles](../understand/principles.md). A change that breaks one is a change of design: open an issue to
  discuss it first.
- Read [Reading the source](source-tour.md) for the rules the code relies on.
- Set up the [test guests](testing.md). Nothing that runs software runs on your own machine, tests included.

## Rules for every change

- **Standard library only**, Python 3.12 or later, Linux on x86-64; Debian 13 and Ubuntu 26.04 are the minimum systems,
  with no workarounds for older ones.
- **Never source, execute or evaluate text from the network**, catalogs included; parse it as data and clean it before
  printing.
- **Tests and documentation in the same commit as the code.** When behaviour changes, update the affected pages of this
  site (the concept page, the guide, the reference, a decision page if a choice was made) and the tests.
- **Both guests pass** before a commit: `tests/vm/test.sh` and `GUEST=ubuntu tests/vm/test.sh`.
- **Licensing:** MPL-2.0, REUSE-compliant at every commit. Every code file starts with
  `SPDX-FileCopyrightText: 2026 Alberto P` and `SPDX-License-Identifier: MPL-2.0` (after a shebang); other files are
  covered by `REUSE.toml`. A new file type needs a header or a `REUSE.toml` entry in the same commit.
- **No personal data** in tracked files or commit messages: no home paths, user names, host names, e-mail addresses
  other than GitHub's no-reply ones, session links or IDs. Use `~` and placeholders. Enable the check once per clone:
  `git config core.hooksPath .githooks`.

## Git

- A feature with several commits goes on its own branch and is merged into `main` with an ordinary merge commit
  (`git merge --no-ff`) whose message says what the branch is for; a single-commit change goes straight onto `main`.
- Commit at each completed, tested step, with a clear message.
- Pushed history is never rewritten.

## Reporting

- Bugs, blocked permissions, unknown Wayland interfaces, app compatibility, feature requests and documentation problems
  have their own issue forms on GitHub; each asks for the details needed to reproduce.
- Vulnerabilities are reported privately: see the
  [security policy](https://github.com/alberto743/appjail/blob/main/SECURITY.md).
