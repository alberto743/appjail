# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import hashlib
import json
import os
import subprocess

import pytest

from bjail import attest, cli, github, jail, manifest, snappy, store, tools
from bjail.github import Client, GitHubError
from .helpers import FakeClient, NEW_IMAGE, NOW, Script, T0, installed, integration, release2


SHA = "a" * 64


# -- snappy ----------------------------------------------------------------------------------


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def test_snappy_literal_and_overlapping_copy():
    data = varint(9) + bytes([2 << 2]) + b"abc" + bytes([5 << 2 | 2]) + (3).to_bytes(2, "little")
    assert snappy.decompress(data) == b"abcabcabc"


def test_snappy_long_literal_and_one_byte_offset_copy():
    text = b"x" * 100
    data = varint(104) + bytes([60 << 2, 99]) + text + bytes([1 | (0 << 2) | (0 << 5), 1])
    assert snappy.decompress(data) == text + b"xxxx"


@pytest.mark.parametrize("data", [
    b"", b"\x80", varint(5) + bytes([4 << 2]) + b"ab",  # truncated literal
    varint(4) + bytes([0]) + b"a" + bytes([1, 5]),  # copy before the start
    varint(3) + bytes([0]) + b"a",  # shorter than announced
    varint(1) + bytes([2 << 2]) + b"abc",  # longer than announced
    varint(10**9),  # over the limit
], ids=["empty", "bad-header", "truncated", "copy-out-of-range", "short", "long", "huge"])
def test_snappy_rejects_malformed_input(data):
    with pytest.raises(snappy.SnappyError):
        snappy.decompress(data)


# -- fetching bundles ------------------------------------------------------------------------

BUNDLE = {"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json", "dsseEnvelope": {}}
BLOB = "https://tmaproduction.blob.core.windows.net/attestations/1/2026/09/30/51"


def listing(*items):
    return {"attestations": list(items)}


def bundle_client(listing_body, blobs=None, status=200):
    calls = []

    def fetch(url, headers, timeout, max_bytes):
        calls.append((url, dict(headers)))
        if url.startswith(github.API):
            return 200, {}, json.dumps(listing_body).encode()
        return status, {}, (blobs or {})[url]
    return Client(token="secret", fetch=fetch), calls


def test_bundle_inline_json_snappy_and_plain_blob():
    raw = json.dumps(BUNDLE).encode()
    packed = varint(len(raw)) + bytes([60 << 2, len(raw) - 1]) + raw
    c, calls = bundle_client(listing({"bundle": BUNDLE}, {"bundle": None, "bundle_url": BLOB},
                                     {"bundle_url": BLOB + "b"}), {BLOB: packed, BLOB + "b": raw})
    assert c.attestation_bundles("o/r", SHA) == [BUNDLE, BUNDLE, BUNDLE]
    blob_calls = [h for u, h in calls if not u.startswith(github.API)]
    assert blob_calls and all("Authorization" not in h for h in blob_calls)  # the token never leaves api.github.com


@pytest.mark.parametrize("url", ["http://x.blob.core.windows.net/a", "https://evil.example/a",
                                 "https://blob.core.windows.net.evil.example/a"])
def test_bundle_url_must_be_azure_blob_https(url):
    c, _ = bundle_client(listing({"bundle_url": url}))
    with pytest.raises(GitHubError, match="storage host"):
        c.attestation_bundles("o/r", SHA)


def test_bundle_download_failure_and_garbage():
    c, _ = bundle_client(listing({"bundle_url": BLOB}), {BLOB: b""}, status=403)
    with pytest.raises(GitHubError, match="HTTP 403"):
        c.attestation_bundles("o/r", SHA)
    c, _ = bundle_client(listing({"bundle_url": BLOB}), {BLOB: b"\xff\xfe not json"})
    with pytest.raises(GitHubError, match="not valid JSON"):
        c.attestation_bundles("o/r", SHA)


def test_no_attestations_and_invalid_digest():
    c, _ = bundle_client(listing())
    assert c.attestation_bundles("o/r", SHA) == []
    with pytest.raises(GitHubError):
        c.attestation_bundles("o/r", "xyz")


# -- reading gh's verdict ---------------------------------------------------------------------


def result(repo="https://github.com/o/App", issuer=attest.ISSUER, owner="42"):
    return {"verificationResult": {"signature": {"certificate": {
        "sourceRepositoryURI": repo, "issuer": issuer, "sourceRepositoryOwnerIdentifier": owner,
        "sourceRepositoryIdentifier": "7", "buildSignerURI": "https://github.com/o/App/.github/workflows/r.yml@refs/heads/main",
        "sourceRepositoryRef": "refs/heads/main", "runInvocationURI": "https://github.com/o/App/actions/runs/1"}}}}


def test_matching_result_is_accepted():
    v = attest.check_results([result()], "o/App", 42)
    assert v.workflow.endswith("r.yml@refs/heads/main") and v.owner_id == "42" and v.repo_id == "7"
    assert attest.check_results([result(repo="https://github.com/O/APP")], "o/App")  # case-insensitive names


@pytest.mark.parametrize("res,match", [
    ([result(repo="https://github.com/o/Other")], "signed for"),
    ([result(issuer="https://accounts.google.com")], "issuer"),
    ([result(owner="99")], "owner account"),
    ([{"nothing": 1}], "unreadable"),
    ([], "none verified"),
    ("garbage", "none verified"),
])
def test_mismatching_results_are_refused(res, match):
    with pytest.raises(attest.AttestError, match=match):
        attest.check_results(res, "o/App", 42)


# -- running gh --------------------------------------------------------------------------------


@pytest.fixture
def fake_gh(sandbox, monkeypatch):
    path = store.tools_dir() / "gh"
    path.parent.mkdir(parents=True)
    path.write_text("x")
    monkeypatch.setattr(tools, "require", lambda name: path)
    return path


def runner_returning(rc=0, out="[]", err=""):
    calls = []

    def run(args, timeout=None, watch=None):
        calls.append(args)
        return subprocess.CompletedProcess(args, rc, out, err)
    run.calls = calls
    return run


def test_verify_runs_gh_in_the_jail_with_the_bundles_and_cleans_up(fake_gh, tmp_path):
    subject = tmp_path / "f"
    subject.write_bytes(b"x")
    run = runner_returning(out=json.dumps([result()]))
    v = attest.verify(subject, "o/App", [BUNDLE], 42, run=run)
    assert v.repo == "https://github.com/o/App"
    args = run.calls[0]
    assert "--share-net" in args and args[args.index("--bundle") + 1] == "/bundle.jsonl"
    assert args[args.index("--repo") + 1] == "o/App" and "--unshare-all" in args
    assert "GITHUB_TOKEN" not in args and not any("secret" in str(a) for a in args)
    assert list(store.staging_root().iterdir()) == []


@pytest.mark.parametrize("rc,out,err,match", [
    (1, "", "Error: verifying with issuer", "verification failed"),
    (0, "not json", "", "not understood"),
])
def test_verify_failures(fake_gh, tmp_path, rc, out, err, match):
    with pytest.raises(attest.AttestError, match=match):
        attest.verify(tmp_path, "o/App", [BUNDLE], run=runner_returning(rc, out, err))


def test_verify_without_bundles_or_tool(sandbox, tmp_path):
    with pytest.raises(attest.AttestError, match="no attestation"):
        attest.verify(tmp_path, "o/App", [])
    with pytest.raises(attest.AttestError, match="bjail tools install gh"):
        attest.verify(tmp_path, "o/App", [BUNDLE])


# -- tiers in add and update -----------------------------------------------------------------


def fake_verify(ok=True):
    calls = []

    def verify(staged, full_name, bundles, owner_id=None):
        calls.append((full_name, owner_id))
        if not ok:
            raise attest.AttestError("signature invalid")
        return attest.check_results([result()], full_name, owner_id)
    verify.calls = calls
    return verify


def add_with(h, client, verify, **kw):
    console = Script(["y"])
    cli.cmd_add(cli.build_parser().parse_args(["add", "o/App"]), client, console, download=h.download(), now=NOW,
                extract=h.extract, extract_ok=lambda: True, verify=verify)
    return console


def test_add_with_a_verified_attestation_is_tier_1(h):
    verify = fake_verify()
    c = add_with(h, FakeClient(bundles=[BUNDLE]), verify)
    assert manifest.load(store.manifest_path("app")).evidence_tier == 1
    assert "attestation verified" in c.text and verify.calls == [("o/App", 42)]


def test_add_with_a_failing_attestation_keeps_tier_3_and_says_why(h):
    c = add_with(h, FakeClient(bundles=[BUNDLE]), fake_verify(ok=False))
    assert manifest.load(store.manifest_path("app")).evidence_tier == 3
    assert "attestation not counted: signature invalid" in c.text


def test_add_without_bundles_never_calls_the_verifier(h):
    verify = fake_verify()
    add_with(h, FakeClient(), verify)
    assert verify.calls == [] and manifest.load(store.manifest_path("app")).evidence_tier == 3


def run_update(h, client, verify, answers=("y",), days=0):
    console = Script(answers)
    args = cli.build_parser().parse_args(["update", "app", "--quarantine", str(days)])
    code = cli.cmd_update(args, client, console, download=h.download(NEW_IMAGE), now=T0, extract=h.extract,
                          extract_ok=lambda: True, verify=verify)
    return code, console


def test_update_can_upgrade_to_tier_1(h):
    path = installed(h)
    run_update(h, FakeClient(release_=release2(), bundles=[BUNDLE]), fake_verify())
    assert manifest.load(path).evidence_tier == 1


def tier1_app(h):
    add_with(h, FakeClient(bundles=[BUNDLE]), fake_verify())
    return store.manifest_path("app")


def test_tier_1_app_blocks_a_release_without_attestation(h):
    path = tier1_app(h)
    before = path.read_text()
    code, c = run_update(h, FakeClient(release_=release2(), attestation=False), fake_verify())
    assert code == 1 and "EVIDENCE DOWNGRADE" in c.text and path.read_text() == before


def test_tier_1_app_refuses_an_attestation_that_does_not_verify(h):
    path = tier1_app(h)
    before = path.read_text()
    code, c = run_update(h, FakeClient(release_=release2(), bundles=[BUNDLE]), fake_verify(ok=False))
    assert code == 1 and "EVIDENCE DOWNGRADE" in c.text and "signature invalid" in c.text
    assert path.read_text() == before


def test_tier_1_app_updates_when_the_new_release_verifies(h):
    path = tier1_app(h)
    code, c = run_update(h, FakeClient(release_=release2(), bundles=[BUNDLE]), fake_verify())
    assert code == 0 and manifest.load(path).version == "v2.0" and manifest.load(path).evidence_tier == 1


# -- the real thing (opt-in: downloads the pinned gh, ~15 MB, and queries GitHub) -----------------

GH_SUBJECT_SHA = tools.TOOLS["gh"].sha256


@integration
@pytest.mark.skipif(os.environ.get("BJAIL_E2E") != "1", reason="set BJAIL_E2E=1 in the test guest (downloads gh, 15 MB)")
def test_real_sigstore_verification_of_a_cli_release(sandbox, tmp_path):
    tools.install("gh")
    # the subject is the very archive the tool was installed from: download it again in the jail
    t = tools.TOOLS["gh"]
    subject = jail.download(t.url, tmp_path, "gh.tar.gz", t.size)
    assert hashlib.sha256(subject.read_bytes()).hexdigest() == GH_SUBJECT_SHA
    bundles = Client().attestation_bundles("cli/cli", GH_SUBJECT_SHA)
    assert bundles
    v = attest.verify(subject, "cli/cli", bundles, owner_id=59704711)
    assert v.repo == "https://github.com/cli/cli" and "deployment.yml" in v.workflow
    with pytest.raises(attest.AttestError):  # another repository's name must not verify
        attest.verify(subject, "cli/go-gh", bundles)
    with pytest.raises(attest.AttestError, match="owner account"):
        attest.verify(subject, "cli/cli", bundles, owner_id=1)
    tampered = tmp_path / "t.tar.gz"
    tampered.write_bytes(subject.read_bytes() + b"x")
    with pytest.raises(attest.AttestError):
        attest.verify(tampered, "cli/cli", bundles)
