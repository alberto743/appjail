# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Run installed apps in appjail's real jail under strace, with the host system view narrowed in four ways (guest only).

Usage: matrix.py APP [SCENARIO...] [--variants C,A,A2,B] [--train SCENARIO] [--json FILE]

Needs ~/appjail (tests/vm/sync.sh), the apps installed with APPJAIL_DATA_DIR and APPJAIL_CONFIG_DIR set, a headless weston on
the socket named by WAYLAND_DISPLAY, and strace. Not run by pytest, and not part of appjail: it replaces `system_args` of
appjail.jail and appjail.runtimejail to build each variant of the view.

Variants:
  C   the view appjail gives today (/usr, /bin, /sbin, /lib*, read-only);
  A   C with /usr/bin, /usr/sbin, /usr/libexec and /usr/share/applications emptied, and only sh and env put back;
  A2  A with the programs the app was seen to run (in the training scenario) put back too;
  B   an empty /usr, /lib*, /bin, /sbin with only the files the training scenario was seen to open, run or stat.
"""

import json
import os
import pty
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path.home() / "appjail" / "src"))
from appjail import jail, runner, runtimejail

RT = Path(f"/run/user/{os.getuid()}")
SEEN = ("/usr/", "/lib/", "/lib64/", "/lib32/", "/bin/", "/sbin/", "/etc/", "/opt/", "/var/", "/srv/")
KEEP = ("sh", "env")
EMPTIED = ("/usr/bin", "/usr/sbin", "/usr/libexec", "/usr/share/applications")
IMG = "/app/AppRun"
FAILED_EXECS = set()
ALL_EXECS = set()
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][B0]|\x1b[=>]")

# Scenario: (command inside the jail after the app, how to drive it). A "pty" scenario sends keys to a terminal app.
SCENARIOS = {
    "htop": {
        "version": (["--version"], None),
        "tui": ([], ("pty", [(2.5, b"q")])),
        "strace-key": ([], ("pty", [(2.5, b"s"), (4.5, b"\x1b"), (5.5, b"q")])),
        "lsof-key": ([], ("pty", [(2.5, b"l"), (4.5, b"\x1b"), (5.5, b"q")])),
    },
    "galculator": {"start": ([], ("gui", 6))},
    "lagrange": {"start": ([], ("gui", 6))},
    "imagemagick": {
        "version": (["-version"], None),
        "png-jpg": (["-size", "64x64", "gradient:red-blue", "/tmp/a.jpg"], None),
        "text": (["-size", "220x40", "xc:white", "-pointsize", "20", "-annotate", "+5+28", "hello", "/tmp/t.png"], None),
        "fonts": (["-list", "font"], None),
        "pdf": (["-size", "10x10", "xc:red", "/tmp/x.pdf"], None),
    },
}
PROBE = """
n() { set -- "$1"/*; [ -e "$1" ] && echo $# || echo 0; }
echo "usr/bin $(n /usr/bin) usr/sbin $(n /usr/sbin) usr/libexec $(n /usr/libexec) share/applications $(n /usr/share/applications)"
echo "usr/lib $(n /usr/lib) lib/x86_64-linux-gnu $(n /usr/lib/x86_64-linux-gnu) share/doc $(n /usr/share/doc) share/fonts $(n /usr/share/fonts)"
echo "libssl $(ls /usr/lib/x86_64-linux-gnu/libssl* 2>/dev/null | tr '\\n' ' ')"
echo "gnu-libc $(ls /usr/lib/x86_64-linux-gnu/libc.so* /lib/x86_64-linux-gnu/libc.so* 2>/dev/null | tr '\\n' ' ')"
echo "/usr/lib/os-release: $(cat /usr/lib/os-release 2>/dev/null | head -2 | tr '\\n' ' ')"
"""


def real(path):
    return os.path.realpath(path)


def variant_args(variant, allow=(), files=None):
    """The replacement of system_args() for a variant."""
    def current():
        args = []
        for d in jail.SYSTEM_DIRS:
            if os.path.islink(d):
                args += ["--symlink", os.readlink(d), d]
            elif os.path.isdir(d):
                args += ["--ro-bind", d, d]
        return args
    if variant == "C":
        return current
    if variant in ("A", "A2"):
        def narrowed():
            args = current()
            emptied = [d for d in EMPTIED if os.path.isdir(d) and not os.path.islink(d)]  # Fedora: /usr/sbin is a link to bin
            for d in emptied:
                args += ["--tmpfs", d]
            programs = [f"/usr/bin/{n}" for n in KEEP] + list(allow if variant == "A2" else ())
            for p in programs:  # put back at the canonical place, nested helpers (/usr/libexec/x/helper) included
                canon = os.path.join(real(os.path.dirname(p)), os.path.basename(p))
                if os.path.lexists(p) and canon.startswith(tuple(d + "/" for d in emptied)):
                    args += ["--ro-bind", real(p), canon]
            for d in emptied:
                args += ["--remount-ro", d]
            return args
        return narrowed

    def traced():  # B: only what the training run touched
        args, links, bound = [], set(), set()
        for d in jail.SYSTEM_DIRS:
            if os.path.islink(d):
                args += ["--symlink", os.readlink(d), d]

        def link(path):  # recreated at its canonical place (/bin/sh is /usr/bin/sh), as the same relative link
            canon = os.path.join(real(os.path.dirname(path)), os.path.basename(path))
            if canon not in links and path not in jail.SYSTEM_DIRS:
                links.add(canon)
                args.extend(["--symlink", os.readlink(path), canon])
        todo = sorted(f for f in files if not f.startswith("/etc/"))
        while todo:
            q = todo.pop(0)
            parts = Path(q).parts
            for i in range(2, len(parts)):  # a symlinked directory on the way (/usr/share/X11/xkb) must exist as one
                if os.path.islink(anc := str(Path(*parts[:i]))):
                    link(anc)
            if os.path.islink(q):  # a link itself (a library soname): recreate it and bind what it points to
                link(q)
                todo.append(real(q))
                continue
            p = os.path.join(real(os.path.dirname(q)), os.path.basename(q))
            if p in bound or any(p.startswith(x + "/") for x in links):
                continue
            bound.add(p)
            args += ["--dir", p] if os.path.isdir(p) else ["--ro-bind", p, p]
        return args
    return traced


def interpreters(path):
    """What the kernel opens when it runs a file, which a trace of open calls never shows: the ELF loader (PT_INTERP) or
    the interpreter of a script (its #! line; for env, the program it names, found on the default PATH)."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
            if head[:2] == b"#!":
                words = (head + f.readline()).split(b"\n")[0][2:].decode(errors="replace").split()
                out = words[:1]
                if words and Path(words[0]).name == "env" and len(words) > 1:
                    out += [str(d / words[-1]) for d in map(Path, ("/usr/bin", "/bin")) if (d / words[-1]).exists()][:1]
                return out
            if head[:4] != b"\x7fELF" or head[4] != 2:
                return []
            phoff, phentsize, phnum = (int.from_bytes(head[32:40], "little"), int.from_bytes(head[54:56], "little"),
                                       int.from_bytes(head[56:58], "little"))
            for i in range(phnum):
                f.seek(phoff + i * phentsize)
                ph = f.read(phentsize)
                if int.from_bytes(ph[0:4], "little") == 3:  # PT_INTERP
                    f.seek(int.from_bytes(ph[8:16], "little"))
                    return [f.read(int.from_bytes(ph[32:40], "little")).split(b"\0")[0].decode()]
    except OSError:
        pass
    return []


def closure(programs, root):
    """Every file the kernel opens on behalf of the programs, recursively; /app/... names are mapped into the app's tree."""
    seen, todo = set(), list(programs)
    while todo:
        p = todo.pop()
        host = str(Path(root) / p[len("/app/"):]) if p.startswith("/app/") else p
        for i in interpreters(host):
            if i not in seen:
                seen.add(i)
                todo.append(i)
    return seen


def parse_trace(path):
    """(executed programs that started, paths that were found, paths that were not found), host paths only."""
    execs, found, missing = set(), set(), set()
    global FAILED_EXECS, ALL_EXECS
    FAILED_EXECS, ALL_EXECS = set(), set()
    pat = re.compile(r'^(?:\d+\s+)?(execve|execveat|openat|open|stat|newfstatat|statx|access|readlink)\((?:AT_FDCWD(?:<[^>]*>)?, |(\d+)<([^>]*)>, )?"([^"]+)".*\) = (-?\d+)(?: (\w+))?')
    unfinished = re.compile(r'^(\d+)\s+(execve|execveat|openat|open|stat|newfstatat|statx|access|readlink)\((?:AT_FDCWD(?:<[^>]*>)?, |(\d+)<([^>]*)>, )?"([^"]+)".*<unfinished \.\.\.>')
    resumed = re.compile(r'^(\d+)\s+<\.\.\. (\w+) resumed>.*\) = (-?\d+)')
    pending = {}  # pid -> (call, path) of a call that strace printed in two halves (threads)

    outer = []  # the first exec is the harness's own bwrap, on the host; a bwrap the app runs later is the app's

    def record(call, name, rc, fd_dir=None):
        p = os.path.join(fd_dir, name) if fd_dir and not name.startswith("/") else name  # -y names the directory fd
        if call.startswith("exec") and not outer:
            outer.append(p)
            return
        if call.startswith("exec") and rc >= 0:
            ALL_EXECS.add(p)
        if not p.startswith(SEEN):
            return
        if rc >= 0:
            found.add(p)
            if call.startswith("exec"):
                execs.add(p)
        elif rc < 0:
            missing.add(p)
            if call.startswith("exec"):
                FAILED_EXECS.add(p)
    for line in Path(path).read_text(errors="replace").splitlines():
        if (m := unfinished.match(line)):
            pending[m.group(1)] = (m.group(2), m.group(5), m.group(4))
        elif (m := resumed.match(line)):
            if (call := pending.pop(m.group(1), None)):
                record(call[0], call[1], int(m.group(3)), call[2])
        elif (m := pat.match(line)):
            record(m.group(1), m.group(4), int(m.group(5)), m.group(3))
    return execs, found, missing


def drive(proc_fd, keys, total):
    start, sent, out = time.time(), 0, b""
    while time.time() - start < total:
        ready, _, _ = select.select([proc_fd], [], [], 0.2)
        if ready:
            try:
                data = os.read(proc_fd, 65536)
            except OSError:
                break
            if not data:
                break
            out += data
        while sent < len(keys) and time.time() - start >= keys[sent][0]:
            os.write(proc_fd, keys[sent][1])
            sent += 1
    return out


def run_once(app, scenario, variant, workdir, allow=(), files=None):
    """Run a scenario in the jail of the app under strace; returns (result dict, trace path)."""
    args, mode = SCENARIOS[app][scenario] if scenario != "probe" else (["sh", "-c", PROBE], None)
    runtimejail.system_args = jail.system_args = variant_args(variant, allow, files)
    m, root, home, etc = runner.prepare(app, say=lambda *_: None)
    for child in Path(home).iterdir():  # every run starts from an empty private home
        shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
    env = {"XDG_RUNTIME_DIR": str(RT), "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY", "wl-a11y"), "LANG": "C.UTF-8"}
    perms = replace(m.permissions, raw_terminal=True) if app == "htop" else m.permissions  # terminal apps need this grant
    if app == "htop":
        env["TERM"] = "xterm"
    inner = [IMG, *args] if scenario != "probe" else args
    argv = [jail.find_bwrap(), *runtimejail.runtime_args(root=root, home=home, etc_dir=etc, perms=perms,
                                                          uid=os.getuid(), host_env=env, command=inner)]
    trace = Path(workdir) / f"{app}-{scenario}-{variant}.trace"
    strace = ["strace", "-f", "-y", "-qq", "-s", "120", "-o", str(trace), "-e",
              "trace=execve,execveat,openat,open,stat,newfstatat,statx,access,readlink"]
    t0 = time.time()
    shown = ""
    if mode and mode[0] == "pty":
        master, slave = pty.openpty()
        proc = subprocess.Popen([*strace, *argv], stdin=slave, stdout=slave, stderr=slave, close_fds=True, start_new_session=True)
        os.close(slave)
        shown = drive(master, mode[1], 8).decode("utf-8", "replace")
        proc.kill()
        proc.wait()
        os.close(master)
        rc = proc.returncode
    else:
        limit = mode[1] if mode else 40
        proc = subprocess.Popen([*strace, *argv], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, start_new_session=True)
        try:
            shown, _ = proc.communicate(timeout=limit)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, 9)
            shown, _ = proc.communicate()
            rc = "up" if mode else "hang"  # a window app still running when the time is up is a start that worked
    execs, found, missing = parse_trace(trace)
    return {"app": app, "scenario": scenario, "variant": variant, "rc": rc, "seconds": round(time.time() - t0, 1),
            "text": ANSI.sub("", shown)[-1200:], "execs": sorted(execs), "failed_execs": sorted(FAILED_EXECS),
            "found": len(found), "missing": sorted(missing - found), "all_execs": sorted(ALL_EXECS), "root": str(root)}, trace


def probe(app):
    """What a program in the jail can list of the host, per variant (needs `sh`, so not for B)."""
    work = tempfile.mkdtemp(prefix="hostview-")
    for v in ("C", "A", "A2"):
        r, _ = run_once(app, "probe", v, work, ("/usr/bin/sh", "/usr/bin/env"))
        print(f"-- {v} (rc={r['rc']})\n" + r["text"].strip())
    shutil.rmtree(work, ignore_errors=True)


def main(argv):
    if argv[0] == "probe":
        return probe(argv[1])
    app = argv[0]
    rest = argv[1:]
    variants = ["C", "A", "A2", "B"]
    train = None
    out_json = None
    names = []
    while rest:
        a = rest.pop(0)
        if a == "--variants":
            variants = rest.pop(0).split(",")
        elif a == "--train":
            train = rest.pop(0)
        elif a == "--json":
            out_json = rest.pop(0)
        else:
            names.append(a)
    names = names or list(SCENARIOS[app])
    train = train or names[0]
    work = tempfile.mkdtemp(prefix="hostview-")
    base, trace = run_once(app, train, "C", work)
    execs, found, _ = parse_trace(trace)
    kernel = closure({*ALL_EXECS, "/app/AppRun"}, base["root"])  # interpreters and loaders the trace cannot show
    allow = sorted(e for e in {*execs, *kernel} if e.startswith(("/usr/bin/", "/usr/sbin/", "/usr/libexec/", "/bin/", "/sbin/")))
    files = {p for p in found if os.path.exists(p)} | {i for i in {*kernel, "/lib64/ld-linux-x86-64.so.2"} if os.path.exists(i)}
    # Every parent directory of a file in the set must exist as a directory, which bwrap creates itself.
    results = [base]
    for sc in names:
        for v in variants:
            if sc == train and v == "C":
                continue
            r, _ = run_once(app, sc, v, work, allow, files)
            results.append(r)
    print(f"app={app} train={train} allowlist(A2)={[Path(a).name for a in allow]} files(B)={len(files)}")
    for r in results:
        ran = sorted({Path(e).name for e in r["execs"]})
        failed = sorted({Path(e).name for e in r["failed_execs"]} - set(ran))
        print(f"{r['scenario']:12} {r['variant']:3} rc={r['rc']!s:<5} ran={ran} not-found={failed} lost-files={len(r['missing'])}")
    if out_json:
        Path(out_json).write_text(json.dumps({"allow": allow, "files": len(files), "results": results}, indent=1))
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1:])
