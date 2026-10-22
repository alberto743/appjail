# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Command line interface: the parser and the dispatcher. The commands live in cmd_*.py.

The names re-exported here are the ones tests and the `appjail` console script (pyproject.toml) import from `appjail.cli`.
"""

import argparse
import sys
from importlib import metadata

from . import github, index, indexsync, jail, manifest, runner, tools, updater
from .cmd_add import cmd_add
from .cmd_apps import cmd_history, cmd_list, cmd_perms, cmd_remove, cmd_tools
from .cmd_index import (
    cmd_index_rollback,
    cmd_index_status,
    cmd_index_update,
    cmd_search,
)
from .cmd_portals import cmd_portals
from .cmd_update import cmd_update
from .console import Abort, Console
from .permargs import PERMISSION_FLAGS, dirs_from_args, files_from_args


class _HelpOnErrorParser(argparse.ArgumentParser):
    """Argument errors show the full help of the parser that failed, not just the usage line.

    The subparsers are created with the class of their parent, so this covers every command.
    """

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n\n")
        self.print_help(sys.stderr)
        self.exit(2)


def version_string():
    """The installed version (from the git tag at build time), or "unknown" when run from a source tree."""
    try:
        return metadata.version("appjail")
    except metadata.PackageNotFoundError:
        return "unknown"


def build_parser():
    p = _HelpOnErrorParser(prog="appjail", description="Sandboxed AppImage manager")
    p.add_argument("--version", action="version", version=f"appjail {version_string()}")
    sub = p.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="add an app from a GitHub owner/repo")
    add.add_argument("source", help="GitHub owner/repo")
    add.add_argument("--name", help="local app name (default: repo name)")
    add.add_argument("--prerelease", action="store_true", help="allow pre-releases")
    add.add_argument("--tag", help="use this release tag instead of the latest release")
    add.add_argument("--dir", action="append", default=[], metavar="PATH[:ro|:rw]",
                     help="let the app see this directory (read-only unless :rw); repeatable")
    add.add_argument("--dbus", action="append", default=[], metavar="NAME",
                     help="let the app talk to this session-bus name through a filtering proxy; repeatable")
    add.add_argument("--dbus-own", action="append", default=[], metavar="NAME",
                     help="let the app own this session-bus name (MPRIS player, single-instance name); repeatable")
    add.add_argument("--portal", action="append", default=[], metavar="NAME",
                     help="also allow this privileged portal interface (needs --allow portals); repeatable")
    add.add_argument("--allow", action="append", default=[], choices=[f for f in PERMISSION_FLAGS if f not in ("audio", "gpu")],
                     help="grant a permission (repeatable); audio and gpu are on by default")
    add.add_argument("--no-audio", action="store_true", help="do not grant audio")
    add.add_argument("--no-gpu", action="store_true", help="do not grant GPU access")
    add.add_argument("--display", choices=manifest.DISPLAYS, default="wayland")
    search = sub.add_parser("search", help="search the local AM index (suggestions only, never installs)")
    search.add_argument("keywords", nargs="+")
    search.add_argument("--limit", type=int, default=20, help="maximum results (default 20)")
    search.add_argument("--all", action="store_true", help="show every match")
    idx = sub.add_parser("index", help="manage the local AM search index")
    isub = idx.add_subparsers(dest="index_command", required=True)
    upd = isub.add_parser("update", help="fetch the AM index, review the changes, then pin it")
    upd.add_argument("--commit", default="HEAD", help="fetch this commit (40 hex digits) instead of the remote HEAD")
    isub.add_parser("rollback", help="go back to the previous index snapshot")
    isub.add_parser("status", help="show the pinned index")
    upd_app = sub.add_parser("update", help="check for a newer release and install it after review and quarantine")
    upd_app.add_argument("app", nargs="?", help="app name (default: every installed app)")
    upd_app.add_argument("--prerelease", action="store_true", help="follow pre-releases for this run (see --channel to make it permanent)")
    upd_app.add_argument("--channel", choices=manifest.CHANNELS, help="set which releases this app follows from now on: stable, prerelease, or pinned (never updated)")
    upd_app.add_argument("--quarantine", type=int, default=updater.DEFAULT_QUARANTINE_DAYS, metavar="DAYS",
                         help="days a new release must wait after it was first seen (default %(default)s; 0 = none)")
    sub.add_parser("list", help="list installed apps")
    sub.add_parser("version", help="show the appjail version")
    tl = sub.add_parser("tools", help="pinned helper binaries (e.g. for DwarFS AppImages)")
    tsub = tl.add_subparsers(dest="tools_command", required=True)
    tsub.add_parser("status", help="show which helpers are installed and intact")
    tinst = tsub.add_parser("install", help="download a helper whose size and sha256 are pinned in appjail's source")
    tinst.add_argument("tool", choices=sorted(tools.TOOLS))
    hist = sub.add_parser("history", help="show the recorded changes to the manifests")
    hist.add_argument("app", nargs="?")
    hist.add_argument("--limit", type=int, default=20)
    rm = sub.add_parser("remove", help="delete an app, including its private home")
    rm.add_argument("app")
    rm.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    por = sub.add_parser("portals", help="list or revoke the files an app was granted through the document portal")
    por.add_argument("app")
    por.add_argument("--revoke", action="append", default=[], metavar="DOC_ID", help="revoke one document grant (repeatable)")
    por.add_argument("--revoke-all", action="store_true", help="revoke every document grant")
    por.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    perms = sub.add_parser("perms", help="show or change an app's permissions (the pinned release is unchanged)")
    perms.add_argument("app")
    perms.add_argument("--allow", action="append", default=[], choices=PERMISSION_FLAGS)
    perms.add_argument("--deny", action="append", default=[], choices=PERMISSION_FLAGS)
    perms.add_argument("--display", choices=manifest.DISPLAYS)
    perms.add_argument("--add-dir", action="append", default=[], metavar="PATH[:ro|:rw]")
    perms.add_argument("--rm-dir", action="append", default=[], metavar="PATH")
    perms.add_argument("--add-dbus", action="append", default=[], metavar="NAME", help="allow talking to this session-bus name")
    perms.add_argument("--rm-dbus", action="append", default=[], metavar="NAME")
    perms.add_argument("--add-dbus-own", action="append", default=[], metavar="NAME", help="allow owning this session-bus name")
    perms.add_argument("--rm-dbus-own", action="append", default=[], metavar="NAME")
    perms.add_argument("--add-portal", action="append", default=[], metavar="NAME", help="also allow this privileged portal interface")
    perms.add_argument("--rm-portal", action="append", default=[], metavar="NAME")
    perms.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    run = sub.add_parser("run", help="run an installed app in its jail")
    run.add_argument("name")
    run.add_argument("--dir", action="append", default=[], metavar="PATH[:ro|:rw]",
                     help="grant this directory for this run only (manifest unchanged); repeatable")
    run.add_argument("--file", action="append", default=[], metavar="PATH[:rw]",
                     help="bind just this file for this run (read-only unless :rw) and pass its in-jail path to the app; repeatable")
    return p


def main(argv=None, client=None, console=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    app_args = []
    if "--" in argv:  # everything after -- belongs to the app
        i = argv.index("--")
        argv, app_args = argv[:i], argv[i + 1:]
    args = build_parser().parse_args(argv)
    console = console or Console()
    try:
        if args.command == "add":
            if not manifest.SOURCE_RE.fullmatch(args.source):
                raise Abort("source must be a GitHub owner/repo")
            cmd_add(args, client or github.Client(), console)
        elif args.command == "index":
            if args.index_command == "update":
                cmd_index_update(args, console)
            elif args.index_command == "rollback":
                cmd_index_rollback(console)
            else:
                cmd_index_status(console)
        elif args.command == "search":
            cmd_search(args, console)
        elif args.command == "update":
            return cmd_update(args, client or github.Client(), console)
        elif args.command == "list":
            cmd_list(console)
        elif args.command == "version":
            console.out(f"appjail {version_string()}")
        elif args.command == "tools":
            cmd_tools(args, console)
        elif args.command == "history":
            cmd_history(args, console)
        elif args.command == "remove":
            cmd_remove(args, console)
        elif args.command == "portals":
            cmd_portals(args, console)
        elif args.command == "perms":
            cmd_perms(args, console)
        elif args.command == "run":
            extra_dirs = dirs_from_args(args.dir)
            extra_files = files_from_args(args.file)
            return runner.launch(args.name, app_args, say=console.out, extra_dirs=extra_dirs, extra_files=extra_files)
    except Abort as e:
        console.out(str(e))
        return 1
    except (github.GitHubError, jail.JailError, jail.RunError, manifest.ManifestError, index.IndexProblem, indexsync.IndexRefused, OSError) as e:
        console.out(f"error: {e}")
        return 1
    return 0
