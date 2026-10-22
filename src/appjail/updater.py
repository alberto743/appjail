# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Update policy: what blocks an update, the quarantine clock, and the pending-candidate state.

No network and no downloads here; `cmd_update` drives the I/O. The pending file records when
a given candidate was first seen, so the delay cannot be shortened by republishing or waiting
on an old `published_at`: a different candidate starts a new clock.
"""

import json
import os
from datetime import UTC, datetime, timedelta

from . import manifest, store

DEFAULT_QUARANTINE_DAYS = 7
TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
# A pending candidate of a `url:` app also keeps what the server said about it (see cmd_updateimage).
PENDING_KEYS = {"key", "tag", "first_seen", "sha256", "size", "chunks", "etag", "last_modified"}


def stamp(when):
    return when.astimezone(UTC).strftime(TIME_FMT)


def parse_stamp(text):
    return datetime.strptime(text, TIME_FMT).replace(tzinfo=UTC)


def candidate_key(release, asset):
    """Identity of a candidate: the digest when GitHub gives one, else tag, publish time and size."""
    return asset.sha256 or f"{release.tag}|{release.published_at}|{asset.size}"


def blocks(m, info, asset, attested=None):
    """Reasons the update must not proceed, whatever the user says.

    attested: for a tier 1 app, whether GitHub holds an attestation for the candidate (None otherwise).
    """
    out = []
    if m.owner_id is not None and info.owner_id != m.owner_id:
        out.append(f"OWNER CHANGE: the repository is now owned by {info.owner} (account id {info.owner_id}), "
                   f"not the account pinned when it was added (id {m.owner_id})")
    if m.evidence_tier == 1 and not attested:
        out.append("EVIDENCE DOWNGRADE: tier 1 -> 3 or 4 (this release has no build attestation on GitHub)")
        return out
    new_tier = 3 if asset.sha256 else 4
    if m.evidence_tier > 1 and new_tier > m.evidence_tier:
        out.append(f"EVIDENCE DOWNGRADE: tier {m.evidence_tier} -> {new_tier} "
                   "(GitHub no longer provides a digest for this asset)")
    return out


def cautions(m, info):
    """Things the user must see and confirm, which do not block."""
    out = []
    if m.owner_id is None:
        out.append("this app was added before owner pinning: the owner account cannot be checked")
    if info.full_name.lower() != m.target.lower():
        out.append(f"the repository was renamed or transferred: {m.target} -> {info.full_name}")
    if info.archived:
        out.append("the repository is archived")
    return out


def is_newer(m, release):
    return release.published_at >= m.published_at


def quarantine_ends(first_seen, days):
    return first_seen + timedelta(days=days)


# -- pending state ----------------------------------------------------------------------


def pending_path(name):
    return store.app_dir(name) / "pending.json"


def load_pending(name):
    """The recorded candidate, or None if absent or unreadable (treated as never seen)."""
    try:
        data = json.loads(pending_path(name).read_text(encoding="utf-8"))
        if (isinstance(data, dict) and {"key", "tag", "first_seen"} <= set(data) <= PENDING_KEYS
                and all(isinstance(v, int) if k == "size" else isinstance(v, str) for k, v in data.items())
                and not isinstance(data.get("size"), bool)):
            parse_stamp(data["first_seen"])
            if any(k in data and not manifest.SHA256_RE.fullmatch(data[k]) for k in ("sha256", "chunks")):
                return None
            return data
    except (OSError, ValueError):
        pass
    return None


def _write_pending(name, data):
    path = pending_path(name)
    tmp = path.with_name(".pending.json.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def note_seen(name, key, tag, now):
    """First-seen time of this candidate, recorded on first sight and kept afterwards."""
    prev = load_pending(name)
    if prev and prev["key"] == key:
        return parse_stamp(prev["first_seen"])
    _write_pending(name, {"key": key, "tag": tag, "first_seen": stamp(now)})
    return now.replace(microsecond=0)


def record_hash(name, key, digest):
    """Remember the sha256 of the pending candidate (tier 4: no GitHub digest to compare with later).

    The hash is compared with the download that is finally installed, so an asset swapped in place
    during the quarantine is noticed. Ignored when the pending candidate is not this one.
    """
    prev = load_pending(name)
    if not prev or prev["key"] != key:
        return
    _write_pending(name, {**prev, "sha256": digest})


def pending_image(name):
    """The candidate AppImage kept during the quarantine of a `url:` app."""
    return store.app_dir(name) / "pending.AppImage"


def record_url_candidate(name, tag, now, digest, fingerprint=None, etag=None, last_modified=None):
    """Start the quarantine of a downloaded `url:` candidate, keyed by its sha256, and remember what the server said
    about it (so a later check can ask whether it still serves the same file)."""
    data = {"key": digest, "tag": tag, "first_seen": stamp(now), "sha256": digest}
    if fingerprint is not None:
        data |= {"size": fingerprint.size, "chunks": fingerprint.chunks}
    data |= {k: v for k, v in (("etag", etag), ("last_modified", last_modified)) if v}
    _write_pending(name, data)


def clear_pending(name):
    pending_path(name).unlink(missing_ok=True)
    pending_image(name).unlink(missing_ok=True)


def installed():
    """Names of the manifests in the config directory, sorted."""
    base = store.config_dir() / "apps"
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.glob("*.toml") if manifest.NAME_RE.fullmatch(p.stem))
