# Menu entry and opening files

```sh
appjail desktop NAME                       # create the entry; lists the file types the app declares and asks
appjail desktop NAME --mime image/png      # offer the app for this file type
appjail desktop NAME --mime-all            # for every type it declares (minus refused ones)
appjail desktop NAME --rw                  # files opened from the menu are writable
appjail desktop NAME --show                # registered, offered and refused types; writes nothing
appjail desktop NAME --remove
appjail desktop --prune                    # remove entries of apps that no longer exist
```

`add ... --desktop` does the same at install time. The entry is written by appjail, not copied from the AppImage, and
always starts the app through `appjail run`; its name ends in "(appjail)". File types appear only under "Open with":
appjail never makes an app the default for anything. Why: [menu entries and opening files](../understand/desktop/menu-entries.md).

Opening a file from the file manager runs `appjail open NAME -- FILE`, which gives the app that one file, read-only
unless the entry was made with `--rw`. You can run it yourself too.

An app with `display = none` cannot have a menu entry, since it would start invisibly.

## Opening links

A link (`gemini://...`, `obsidian://...`, a login callback) opens a jailed app only if you grant its scheme first. Nothing
is granted by default, and appjail never makes an app the default handler of anything.

```sh
appjail perms NAME --add-scheme gemini      # or: appjail add ... --scheme gemini
appjail desktop NAME                        # rewrite the entry: it now lists the scheme (if the app declares it)
appjail open NAME -- gemini://example.org/  # what a click runs; you can run it yourself
appjail perms NAME --rm-scheme gemini       # take it back
```

`desktop` writes `x-scheme-handler/gemini` into the entry only when the scheme is granted *and* the app's own entry
declares it; it says which granted scheme the app does not declare. A scheme that is not in the list, `file` and anything
that is not a valid link are refused before the app starts.

- **The app is not running:** `appjail open` starts it with the link as its argument.
- **The app is running** (and was started with a scheme granted): the link is sent to it and appjail says so. A relay
  inside the jail starts the app's own handover for it (`AppRun LINK`), so a single-instance app such as a browser or a
  chat client receives it in the instance that is already open, instead of starting a second one.
- **You gave files as well:** a file is bound into a jail when the jail starts, so a running app cannot be given one. The
  app is started again, as for a file, with the links as arguments: while one is running that is a second launch of it, and nothing is relayed.

What can go wrong, in plain terms:

- An app whose own single-instance check does not work in a jail gets nothing from the relay (Joplin's needs `network`,
  and still loses some links).
- appjail gets no reply from the relay. If the app ignores a link it was handed, appjail cannot know.
- A flood of links is slowed down (at most 50 handovers at once, then 20 a second) and the sender is told when the queue
  is full.
- A link sent in the moment the app is ending can be lost without a message.

Why, and what was measured: [links reach a running app through a relay](../decisions/desktop/url-handlers.md).
