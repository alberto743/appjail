# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""A Claude Code PreToolUse hook for Bash: on the host, only an allowlist runs (CLAUDE.md, Hard rules).

Allowed: git (without the options that run other programs), the repository's tracked and unmodified tests/vm/*.sh and
tests/container/run.sh (they start qemu, ssh into the guest and run podman), read-only gh commands and read-only text
utilities. Everything else is denied, whatever the permission mode: interpreters, shells, absolute paths, wrappers, an
environment set before a command, writes through redirection outside /dev/null and the scratchpad.

The hook prints nothing for an allowed command (the usual permission rules then apply) and a deny decision with its
reason otherwise. It is stdlib only and never runs the command it checks.
"""

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

READ_ONLY = {
    "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "find", "stat", "file", "diff", "cmp", "sort",
    "uniq", "cut", "tr", "echo", "printf", "pwd", "date", "realpath", "readlink", "dirname", "basename", "sha256sum",
    "sha512sum", "md5sum", "jq", "tree", "test", "[", "true", "false", "seq", "paste", "column", "comm", "nl", "od",
    "cd", "read", "break", "continue", "exit",
}
SCRIPTS = re.compile(r"tests/vm/[A-Za-z0-9_.-]+\.sh|tests/container/run\.sh")
SCRIPT_ENV = {"GUEST"}  # the only variable set before a command: GUEST=ubuntu tests/vm/test.sh
KEYWORDS = {"then", "else", "do", "!", "if", "elif", "while", "until", "{"}  # a command follows
CLOSERS = {"fi", "done", "}"}
OPERATORS = {"&&", "||", ";", "|", "|&", "&", ";;", "\n"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>", ">&", "<", "<<", "<<-", "<<<", "<>", "<&"}
WRITES = {">", ">>", ">|", "&>", "&>>", "<>"}
SAFE_TARGETS = {"/dev/null", "/dev/stdout", "/dev/stderr"}
SUBST = "\x00subst\x00"  # stands for a checked substitution's output

# options and subcommands through which these tools run another program
GIT_GLOBAL_DENY = ("-c", "--config-env", "--exec-path", "--upload-pack", "--receive-pack")
GIT_DENY = {
    "submodule": {"foreach"}, "bisect": {"run"}, "rebase": {"-x", "--exec"}, "difftool": {"-x", "--extcmd", "-t", "--tool"},
}
GIT_DENY_COMMANDS = {"filter-branch", "filter-repo", "mergetool", "daemon", "instaweb", "credential", "archimport"}
GIT_CONFIG_READ = {"--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin", "--show-scope", "get", "list"}
GIT_CONFIG_WRITE = {"--unset", "--unset-all", "--add", "--replace-all", "--rename-section", "--remove-section", "--edit",
                    "-e", "set", "unset", "edit", "rename-section", "remove-section"}
GH_READ = {
    "run": {"list", "view", "watch"}, "pr": {"list", "view", "checks", "diff", "status"}, "issue": {"list", "view"},
    "release": {"list", "view"}, "repo": {"view"}, "workflow": {"list", "view"},
}
GH_API_WRITE = ("-X", "--method", "-f", "-F", "--field", "--raw-field", "--input")
FIND_DENY = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
SED_WRITE = re.compile(r"(^|[;{}\s!])\s*[0-9$,/]*\s*[ewWrR](\s|$)")
SED_SUBST = re.compile(r"s(.)(?:\\.|(?!\1).)*\1(?:\\.|(?!\1).)*\1([A-Za-z0-9]*)")


class Denied(Exception):
    pass


def _heredocs(text):
    """Remove each heredoc body (data, not commands); an unquoted one expands, so its substitutions are checked."""
    lines = text.split("\n")
    out, pending, expand = [], [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        for m in re.finditer(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2", line):
            pending.append((m.group(3), m.group(1) == "-", not m.group(2)))
        i += 1
        while pending and i <= len(lines):
            word, strip, unquoted = pending.pop(0)
            body = []
            while i < len(lines) and (lines[i].lstrip("\t") if strip else lines[i]) != word:
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                raise Denied(f"heredoc {word!r} is not closed")
            i += 1
            if unquoted:
                expand.append("\n".join(body))
    return "\n".join(out), expand


def _substitutions(text, check):
    """Check each $(...), `...`, <(...) and >(...) outside single quotes as a command of its own, and stand a
    placeholder in its place. Returns the text with the placeholders."""
    out, i, quote = [], 0, None
    while i < len(text):
        c = text[i]
        if quote == "'":
            out.append(c)
            quote = None if c == "'" else quote
            i += 1
            continue
        if c == "\\" and i + 1 < len(text):
            out.append(text[i:i + 2])
            i += 2
            continue
        if c == "'" and quote is None:
            quote = "'"
        elif c == '"':
            quote = None if quote == '"' else '"'
        if text.startswith("$((", i):
            raise Denied("arithmetic expansion is not checked; write the number")
        if c in "$<>" and text.startswith("(", i + 1) and (c == "$" or quote is None):
            depth, j = 1, i + 2
            while j < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            if depth:
                raise Denied("unbalanced command substitution")
            check(text[i + 2:j - 1])
            out.append(SUBST)
            i = j
            continue
        if c == "`":
            j = text.find("`", i + 1)
            if j < 0:
                raise Denied("unbalanced backticks")
            check(text[i + 1:j])
            out.append(SUBST)
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _tokens(text):
    lexer = shlex.shlex(text, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""  # shlex would end a word at a '#' inside it; bash would not, and runs what follows
    try:
        return list(lexer)
    except ValueError as e:
        raise Denied(f"cannot parse the command: {e}") from None


def _commands(tokens):
    """Split into simple commands, taking redirections out (each checked); yields the word lists."""
    words = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in OPERATORS:
            if words:
                yield words
            words = []
        elif tok in ("(", ")"):
            raise Denied("subshells and functions are not allowed")
        elif tok in REDIRECTS:
            target = tokens[i + 1] if i + 1 < len(tokens) else ""
            if tok in WRITES or (tok == ">&" and not target.isdigit() and target != "-"):
                _write_target(target)
            if words and words[-1].isdigit():
                words.pop()  # the file descriptor of 2>&1
            i += 1
        else:
            words.append(tok)
        i += 1
    if words:
        yield words


def _write_target(target):
    if target in SAFE_TARGETS:
        return
    scratch = f"/tmp/claude-{os.getuid()}/"
    resolved = os.path.normpath(target)
    if target.startswith("/") and (resolved + "/").startswith(scratch):
        return
    raise Denied(f"writing to {target!r} through a redirection: use the Write or Edit tool, or the scratchpad")


def _check_words(words, project, tracked):
    for n, word in enumerate(words):
        if word.startswith("#"):  # a comment to the end of the line; the words after a ';' on it are still checked
            words = words[:n]
            break
    while words and words[0] in KEYWORDS:
        words = words[1:]
    if not words or words[0] in CLOSERS:
        return
    if words[0] == "for":  # for NAME in WORDS: no command of its own
        return
    env = []
    while words and re.match(r"[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        env.append(words[0].split("=", 1)[0])
        words = words[1:]
    if not words:
        return  # a plain assignment
    name, args = words[0], words[1:]
    script = _script(name, project)
    if not script and (SUBST in name or "$" in name):
        raise Denied("a command named by an expansion is not allowed")
    if env and (not script or set(env) - SCRIPT_ENV):
        raise Denied(f"setting {', '.join(env)} before a command is not allowed (only GUEST= before a repository script)")
    if script:
        if not tracked(script):
            raise Denied(f"{script} is not tracked by git or differs from HEAD: commit it first, so it is reviewed")
        return
    if "/" in name:
        raise Denied(f"{name!r}: on the host only the repository's tests/vm/*.sh and tests/container/run.sh run by path")
    if name == "git":
        return _git(args)
    if name == "gh":
        return _gh(args)
    if name == "sed":
        return _sed(args)
    if name not in READ_ONLY:
        raise Denied(f"{name!r} does not run on the host: run it in the guest (tests/vm/ssh.sh) or the tooling container")
    if name == "find" and FIND_DENY & set(args):
        raise Denied("find with an action that runs or writes")
    if name == "rg" and any(a == "--pre" or a.startswith("--pre=") for a in args):
        raise Denied("rg --pre runs a program")
    if name == "sort" and any(a.startswith(("--compress-program", "-o", "--output")) for a in args):
        raise Denied("sort with an output file or a compressor")
    if name == "tree" and any(a == "-o" or a.startswith("-o") for a in args):
        raise Denied("tree with an output file")


def _script(name, project):
    """The repository-relative path when `name` is one of the repository's scripts, else None."""
    path = name
    for prefix in ("$CLAUDE_PROJECT_DIR/", "${CLAUDE_PROJECT_DIR}/", f"{project}/", "./"):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    path = os.path.normpath(path)
    return path if SCRIPTS.fullmatch(path) else None


def _git(args):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        if a in GIT_GLOBAL_DENY or a.startswith(tuple(o + "=" for o in GIT_GLOBAL_DENY if o.startswith("--"))):
            raise Denied(f"git {a} can run another program")
        i += 2 if a in ("-C", "--git-dir", "--work-tree", "--namespace") else 1
    if i >= len(args):
        return
    sub, rest = args[i], args[i + 1:]
    if sub in GIT_DENY_COMMANDS:
        raise Denied(f"git {sub} runs other programs")
    if sub in GIT_DENY and GIT_DENY[sub] & {r.split("=", 1)[0] for r in rest}:
        raise Denied(f"git {sub} with an option that runs a program")
    if sub == "config" and (GIT_CONFIG_WRITE & set(rest) or (
            not GIT_CONFIG_READ & set(rest) and len([r for r in rest if not r.startswith("-")]) != 1)):
        raise Denied("git config may only read here: a setting can make git run a program")
    if any(r.startswith(("--upload-pack", "--receive-pack")) or r == "--exec" for r in rest):
        raise Denied("git with an option that runs a program")


def _gh(args):
    if len(args) >= 2 and args[1] in GH_READ.get(args[0], ()):
        return
    if args and args[0] == "api":
        if any(a in GH_API_WRITE or a.startswith(tuple(w + "=" for w in GH_API_WRITE if w.startswith("--"))) for a in args):
            raise Denied("gh api may only read (GET) here")
        return
    raise Denied("only read-only gh commands run here (run, pr, issue, release, repo, workflow: list/view; api GET)")


def _sed(args):
    scripts, i = [], 0
    while i < len(args):
        a = args[i]
        if a.startswith(("-i", "--in-place")) or (a.startswith("-") and not a.startswith("--") and "i" in a[1:]):
            raise Denied("sed -i edits files: use the Edit tool")
        if a in ("-e", "--expression"):
            scripts.append(args[i + 1] if i + 1 < len(args) else "")
            i += 2
            continue
        if a in ("-f", "--file") or a.startswith("--file="):
            raise Denied("sed -f reads a script from a file")
        if not a.startswith("-") and not scripts:
            scripts.append(a)
        i += 1
    for s in scripts:
        if SED_WRITE.search(s) or any(set(m.group(2)) & {"e", "w"} for m in SED_SUBST.finditer(s)):
            raise Denied("a sed script that runs a command or writes a file")


def check(command, project, tracked):
    """None when `command` may run on the host, else the reason it may not."""
    try:
        _check(command, project, tracked)
    except Denied as e:
        return str(e)
    return None


def _check(command, project, tracked):
    text, expanding = _heredocs(command)
    for body in expanding:
        _substitutions(body, lambda inner: _check(inner, project, tracked))
    text = _substitutions(text, lambda inner: _check(inner, project, tracked))
    for words in _commands(_tokens(text)):
        _check_words(words, project, tracked)


def tracked_unmodified(project):
    def tracked(path):
        def git(*args):
            return subprocess.run(["git", "-C", project, *args], capture_output=True, check=False).returncode == 0
        return git("ls-files", "--error-unmatch", "--", path) and git("diff", "--quiet", "HEAD", "--", path)
    return tracked


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {}
    if event.get("tool_name") != "Bash":
        return 0
    project = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    project = str(Path(project).resolve())
    reason = check(str(event.get("tool_input", {}).get("command", "")), project, tracked_unmodified(project))
    if reason:
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                          "permissionDecisionReason": f"host-exec-guard: {reason}"}}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
