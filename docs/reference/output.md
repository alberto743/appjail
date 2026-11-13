# Output

How appjail prints, for scripts and for reading.

- **Streams.** Results and warnings go to standard output, so a warning stays next to the step that caused it. Errors go
  to standard error, as `error: ...`; a plain `cancelled` has no prefix. Warnings are `! warning: ...`.
- **Exit status.** 0 success, 1 error, refusal or cancellation (and for `update`, any app blocked, failed or not checked),
  2 usage error, 130 after Ctrl-C.
- **JSON.** `list --json`, `search --json` and `index status --json` print one JSON document (ASCII only) and nothing
  else. `list --json` always includes the permissions; an unreadable manifest gives an object with `error`. No other
  command has `--json`: their output is a conversation with prompts.
- **Text.** Every line passes through the text cleaner, which removes terminal control sequences and invisible or
  bidirectional characters from untrusted text. Colour is used only for the `warning:` and `error:` prefixes, only on a
  terminal, never with `NO_COLOR` or `TERM=dumb`. On a terminal, long lines wrap at its width with a hanging indent; in a
  pipe or a log each message stays on one line.
- **Confirmations.** Prompts default to No. `remove`, `perms`, `portals` and `desktop` accept `--yes`; `desktop --remove`
  and `--prune`, which only delete appjail's own entries, and `index rollback`, which can be undone, do not ask.
