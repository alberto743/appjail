# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Build-attestation verification (evidence tier 1) with the pinned GitHub CLI, inside a jail.

appjail fetches the Sigstore bundles itself (`github.Client.attestation_bundles`) and hands them to
`gh attestation verify --bundle`, which checks the signature chain against the Sigstore trusted root
(fetched over TUF, hence the network), that the bundle covers the exact downloaded bytes, and that the
signing identity belongs to the repository. `gh` runs from `appjail.tools` (size and sha256 pinned),
sees only the subject, the bundles and a scratch directory, and receives no token (it requires one to
be set but never uses it with `--bundle`). On top of gh's verdict appjail re-reads the certificate
fields and requires GitHub Actions as issuer, the exact repository, and, when known, the pinned
owner account id: a name is not enough, an account id is.
"""

import json
import secrets
import shutil
from dataclasses import dataclass

from . import jail, store, tools
from .textsafe import clean

ISSUER = "https://token.actions.githubusercontent.com"
TIMEOUT = 180


class AttestError(Exception):
    """The attestation could not be verified (tool missing, no valid bundle, identity mismatch)."""


@dataclass(frozen=True)
class Verified:
    repo: str  # https://github.com/owner/repo
    workflow: str  # signing workflow with ref, from the certificate
    ref: str
    run_url: str
    owner_id: str
    repo_id: str


def _args(gh, subject, bundles, scratch):
    return (jail.common_args() + ["--share-net"] + jail.etc_args(private_net=True)
            + ["--ro-bind", str(gh), "/gh", "--ro-bind", str(subject), "/subject",
               "--ro-bind", str(bundles), "/bundle.jsonl", "--bind", str(scratch), "/scratch",
               "--remount-ro", "/", "--chdir", "/scratch",
               "--setenv", "HOME", "/scratch", "--setenv", "GH_TOKEN", "unused",
               "--setenv", "GH_PROMPT_DISABLED", "1", "--setenv", "GH_NO_UPDATE_NOTIFIER", "1", "--"])


def check_results(results, full_name, owner_id=None):
    """First verified result whose certificate matches the repository (and owner id); else AttestError."""
    wanted = f"https://github.com/{full_name}".lower()
    problems = []
    for item in results if isinstance(results, list) else []:
        try:
            cert = item["verificationResult"]["signature"]["certificate"]
            repo = str(cert["sourceRepositoryURI"])
            if repo.lower() != wanted:
                problems.append(f"signed for {repo}")
            elif cert.get("issuer") != ISSUER:
                problems.append(f"unexpected issuer {cert.get('issuer')}")
            elif owner_id is not None and str(cert.get("sourceRepositoryOwnerIdentifier")) != str(owner_id):
                problems.append("the signing repository's owner account differs from the pinned owner")
            else:
                return Verified(repo, str(cert.get("buildSignerURI", "")), str(cert.get("sourceRepositoryRef", "")),
                                str(cert.get("runInvocationURI", "")), str(cert.get("sourceRepositoryOwnerIdentifier", "")),
                                str(cert.get("sourceRepositoryIdentifier", "")))
        except (KeyError, TypeError):
            problems.append("unreadable verification result")
    raise AttestError("no attestation matches this repository: " + ("; ".join(sorted(set(problems))) or "none verified"))


def verify(subject, full_name, bundles, owner_id=None, run=jail.run):
    """Verify the downloaded file against its bundles. Returns Verified or raises AttestError."""
    if not bundles:
        raise AttestError("GitHub holds no attestation for this file")
    try:
        gh = tools.require("gh")
    except tools.ToolError as e:
        raise AttestError(str(e)) from e
    work = store.staging_root() / ("attest-" + secrets.token_hex(8))
    work.mkdir(parents=True, mode=0o700)
    try:
        bundle_file = work / "bundle.jsonl"
        bundle_file.write_text("".join(json.dumps(b) + "\n" for b in bundles), encoding="utf-8")
        scratch = work / "scratch"
        scratch.mkdir(mode=0o700)
        cmd = ["/gh", "attestation", "verify", "/subject", "--repo", full_name, "--bundle", "/bundle.jsonl",
               "--format", "json"]
        try:
            proc = run(_args(gh, subject, bundle_file, scratch) + cmd, timeout=TIMEOUT)
        except jail.JailError as e:
            raise AttestError(str(e)) from e
        if proc.returncode != 0:
            raise AttestError("verification failed: " + clean(proc.stderr.strip() or f"exit {proc.returncode}", 300))
        try:
            results = json.loads(proc.stdout)
        except ValueError as e:
            raise AttestError("verification output was not understood") from e
        return check_results(results, full_name, owner_id)
    finally:
        shutil.rmtree(work, ignore_errors=True)
