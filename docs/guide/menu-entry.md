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
