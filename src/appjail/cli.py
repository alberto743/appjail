# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Command line interface: the parser and the dispatcher. The commands live in cmd_*.py.

The names re-exported here are the ones tests and the `appjail` console script (pyproject.toml) import from `appjail.cli`.
"""

import argparse
import sys
from importlib import metadata

from . import github, jail, manifest, runner, tools, updater
from .catalog import IndexProblem
from .cmd_add import cmd_add
from .cmd_addimage import cmd_add_file, cmd_add_url
from .cmd_apps import cmd_history, cmd_list, cmd_perms, cmd_remove, cmd_tools
from .cmd_desktop import cmd_desktop
from .cmd_index import (
    cmd_index_add,
    cmd_index_remove,
    cmd_index_rollback,
    cmd_index_status,
    cmd_index_update,
    cmd_search,
)
from .cmd_open import cmd_open
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
    add = sub.add_parser("add", help="add an app from a GitHub owner/repo, a local AppImage (--file) or a URL (--url)")
    add.add_argument("source", nargs="?", help="GitHub owner/repo (not with --file or --url)")
    add.add_argument("--file", metavar="PATH", help="install this local AppImage instead of a GitHub release")
    add.add_argument("--url", metavar="URL", help="install the AppImage at this https URL instead of a GitHub release")
    add.add_argument("--sha256", metavar="HEX", help="with --file or --url: the hash the publisher gives; a mismatch aborts, a match makes it tier 4")
    add.add_argument("--max-size", type=int, metavar="MIB", help="with --url: refuse to download more than this (default 1024)")
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
    add.add_argument("--desktop", action="store_true", help="also create a menu entry that starts the app through appjail")
    add.add_argument("--mime", action="append", default=[], metavar="TYPE",
                     help="with --desktop: offer the app for this file type (must be declared by the app); repeatable")
    add.add_argument("--mime-all", action="store_true", help="with --desktop: offer every file type the app declares (minus refused ones)")
    search = sub.add_parser("search", help="search the local AM index (suggestions only, never installs)")
    search.add_argument("keywords", nargs="+")
    search.add_argument("--limit", type=int, default=20, help="maximum results (default 20)")
    search.add_argument("--all", action="store_true", help="show every match")
    idx = sub.add_parser("index", help="manage the catalogs `search` reads (the built-in AM list and any you add)")
    isub = idx.add_subparsers(dest="index_command", required=True)
    upd = isub.add_parser("update", help="refresh the catalogs, review the changes, then accept them")
    upd.add_argument("name", nargs="?", help="one source (default: every source)")
    upd.add_argument("--commit", default="HEAD", help="am only: fetch this commit (40 hex digits) instead of the remote HEAD")
    iadd = isub.add_parser("add", help="add a catalog in the appjail-catalog format (see the README, Search)")
    iadd.add_argument("name", help="a short name for the source")
    where = iadd.add_mutually_exclusive_group(required=True)
    where.add_argument("--url", help="an https URL serving the catalog")
    where.add_argument("--file", help="a local catalog file")
    irm = isub.add_parser("remove", help="remove a source you added, with its catalogs")
    irm.add_argument("name")
    irb = isub.add_parser("rollback", help="go back to the previous catalog of a source")
    irb.add_argument("name", nargs="?", help="default: am")
    isub.add_parser("status", help="list the sources and their catalogs")
    upd_app = sub.add_parser("update", help="check for a newer release and install it after review and quarantine")
    upd_app.add_argument("app", nargs="?", help="app name (default: every installed app)")
    upd_app.add_argument("--prerelease", action="store_true", help="follow pre-releases for this run (see --channel to make it permanent)")
    upd_app.add_argument("--channel", choices=manifest.CHANNELS, help="set which releases this app follows from now on: stable, prerelease, or pinned (never updated)")
    upd_app.add_argument("--quarantine", type=int, default=updater.DEFAULT_QUARANTINE_DAYS, metavar="DAYS",
                         help="days a new release must wait after it was first seen (default %(default)s; 0 = none)")
    upd_app.add_argument("--file", metavar="PATH", help="an app installed from a file: replace it with this AppImage")
    upd_app.add_argument("--sha256", metavar="HEX", help="url/file apps: the hash the publisher gives for the new content (keeps or earns tier 4)")
    upd_app.add_argument("--verify", action="store_true", help="url apps: at the end of the quarantine download the file again and compare it with the candidate")
    sub.add_parser("list", help="list installed apps")
    dsk = sub.add_parser("desktop", help="create, refresh or remove the menu entry of an app")
    dsk.add_argument("app", nargs="?")
    dsk.add_argument("--mime", action="append", default=[], metavar="TYPE", help="offer the app for this file type (repeatable)")
    dsk.add_argument("--mime-all", action="store_true", help="offer every file type the app declares (minus refused ones)")
    dsk.add_argument("--rw", action="store_true", help="opened files are writable (default: read-only)")
    dsk.add_argument("--remove", action="store_true", help="delete the app's menu entry and icons")
    dsk.add_argument("--prune", action="store_true", help="delete the entries of apps that no longer exist")
    dsk.add_argument("--yes", action="store_true", help="do not ask (registers no file types unless --mime/--mime-all)")
    opn = sub.add_parser("open", help="open files with an app, each bound alone into its jail (used by the menu entry)")
    opn.add_argument("app")
    opn.add_argument("files", nargs="*", help="files; put them after -- when a name could look like an option")
    opn.add_argument("--rw", action="store_true", help="the app may write to the files (default: read-only)")
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


def _add(args, client, console, app_args):
    if args.file or args.url:
        if args.source or (args.file and args.url):
            raise Abort("give either a GitHub owner/repo, --file PATH or --url URL")
        (cmd_add_file if args.file else cmd_add_url)(args, console)
        return
    if not args.source or not manifest.REPO_RE.fullmatch(args.source):
        raise Abort("source must be a GitHub owner/repo (or use --file / --url)")
    if args.sha256 or args.max_size:
        raise Abort("--sha256 and --max-size apply to --file / --url only")
    cmd_add(args, client or github.Client(), console)


def _index(args, client, console, app_args):
    return {"update": lambda: cmd_index_update(args, console),
            "add": lambda: cmd_index_add(args, console),
            "remove": lambda: cmd_index_remove(args, console),
            "rollback": lambda: cmd_index_rollback(args, console),
            "status": lambda: cmd_index_status(console)}[args.index_command]()


def _run(args, client, console, app_args):
    return runner.launch(args.name, app_args, say=console.out, extra_dirs=dirs_from_args(args.dir),
                         extra_files=files_from_args(args.file))


# command -> handler(args, client, console, app_args); the return value, if any, is the exit status
COMMANDS = {
    "add": _add,
    "index": _index,
    "search": lambda args, client, console, app_args: cmd_search(args, console),
    "update": lambda args, client, console, app_args: cmd_update(args, client or github.Client(), console),
    "list": lambda args, client, console, app_args: cmd_list(console),
    "version": lambda args, client, console, app_args: console.out(f"appjail {version_string()}"),
    "desktop": lambda args, client, console, app_args: cmd_desktop(args, console),
    "open": lambda args, client, console, app_args: cmd_open(args, [*args.files, *app_args], console),
    "tools": lambda args, client, console, app_args: cmd_tools(args, console),
    "history": lambda args, client, console, app_args: cmd_history(args, console),
    "remove": lambda args, client, console, app_args: cmd_remove(args, console),
    "portals": lambda args, client, console, app_args: cmd_portals(args, console),
    "perms": lambda args, client, console, app_args: cmd_perms(args, console),
    "run": _run,
}


def main(argv=None, client=None, console=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    app_args = []
    if "--" in argv:  # everything after -- belongs to the app
        i = argv.index("--")
        argv, app_args = argv[:i], argv[i + 1:]
    args = build_parser().parse_args(argv)
    console = console or Console()
    try:
        status = COMMANDS[args.command](args, client, console, app_args)
    except Abort as e:
        console.out(str(e))
        return 1
    except (github.GitHubError, jail.JailError, jail.RunError, manifest.ManifestError, IndexProblem, OSError) as e:
        console.out(f"error: {e}")
        return 1
    return status or 0
