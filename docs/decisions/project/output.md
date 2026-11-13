# One output vocabulary, errors on stderr

*Decision on [the project](index.md).*

**Context.** `list` once printed every field of an app on one line, and the commands used four different label styles,
which made output hard to scan.

**Decision.** Every command prints through one small vocabulary (labelled values, tables, bullets, notes, warnings,
errors) and every line passes through the text cleaner first. Errors go to standard error; results and warnings go to
standard output, so a warning stays next to the step that caused it and a pipe or script sees only results. `list` is a
table, and the permissions moved to `list -l`. Colour only on a terminal, only on the warning and error prefixes, and
never with `NO_COLOR` or a dumb terminal. `--json` exists on the three read-only listing commands only (`list`, `search`,
`index status`).

**Rejected.** A formatting library (standard-library rule); `--json` on commands that change something (their output is a
conversation with prompts, and scripts have `--yes` where it is allowed); colour everywhere (it breaks pipes and logs).

**Consequences.** Scripts that matched the old text had to change. The window shows the same text in its output pane.
