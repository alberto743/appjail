# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Update policy: what blocks an update, the quarantine clock, and the pending-candidate state.

No network and no downloads here; `cli.cmd_update` drives the I/O. The pending file records when
a given candidate was first seen, so the delay cannot be shortened by republishing or waiting
on an old `published_at`: a different candidate starts a new clock.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from . import manifest, store

DEFAULT_QUARANTINE_DAYS = 7
TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


def stamp(when):
    return when.astimezone(timezone.utc).strftime(TIME_FMT)


def parse_stamp(text):
    return datetime.strptime(text, TIME_FMT).replace(tzinfo=timezone.utc)


def candidate_key(release, asset):
    """Identity of a candidate: the digest when GitHub gives one, else tag, publish time and size."""
    return asset.sha256 or f"{release.tag}|{release.published_at}|{asset.size}"


def blocks(m, info, asset):
    """Reasons the update must not proceed, whatever the user says."""
    out = []
    if m.owner_id is not None and info.owner_id != m.owner_id:
        out.append(f"OWNER CHANGE: the repository is now owned by {info.owner} (account id {info.owner_id}), "
                   f"not the account pinned when it was added (id {m.owner_id})")
    new_tier = 3 if asset.sha256 else 4
    if new_tier > m.evidence_tier:
        out.append(f"EVIDENCE DOWNGRADE: tier {m.evidence_tier} -> {new_tier} "
                   "(GitHub no longer provides a digest for this asset)")
    return out


def cautions(m, info):
    """Things the user must see and confirm, which do not block."""
    out = []
    if m.owner_id is None:
        out.append("this app was added before owner pinning: the owner account cannot be checked")
    if info.full_name.lower() != m.source.lower():
        out.append(f"the repository was renamed or transferred: {m.source} -> {info.full_name}")
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
        if (isinstance(data, dict) and set(data) == {"key", "tag", "first_seen"}
                and all(isinstance(data[k], str) for k in data)):
            parse_stamp(data["first_seen"])
            return data
    except (OSError, ValueError):
        pass
    return None


def note_seen(name, key, tag, now):
    """First-seen time of this candidate, recorded on first sight and kept afterwards."""
    prev = load_pending(name)
    if prev and prev["key"] == key:
        return parse_stamp(prev["first_seen"])
    path = pending_path(name)
    tmp = path.with_name(".pending.json.tmp")
    tmp.write_text(json.dumps({"key": key, "tag": tag, "first_seen": stamp(now)}), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return now.replace(microsecond=0)


def clear_pending(name):
    pending_path(name).unlink(missing_ok=True)


def installed():
    """Names of the manifests in the config directory, sorted."""
    base = store.config_dir() / "apps"
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.glob("*.toml") if manifest.NAME_RE.fullmatch(p.stem))
