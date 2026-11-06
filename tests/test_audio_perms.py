# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The `mic` permission and the `audio_mode` setting: manifest, command line and warnings (the runner is in test_audiojail.py)."""

import pytest

from appjail import cli, manifest, store
from appjail.manifest import Manifest, ManifestError, Permissions

from .helpers import Script, permission_lines_text


def sample(**perms):
    return Manifest("app", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage", permissions=Permissions(**perms))


def perms(h, *argv, answers=("y",)):
    c = Script(answers)
    cli.cmd_perms(cli.build_parser().parse_args(["perms", "app", *argv]), c)
    return c


def saved():
    return manifest.load(store.manifest_path("app")).permissions


# -- manifest ----------------------------------------------------------------------------


def test_defaults_are_playback_only_and_the_private_pipewire():
    p = Permissions()
    assert (p.audio, p.mic, p.audio_mode) == (False, False, "pipewire")


def test_mic_and_a_non_default_mode_are_written_only_when_set():
    text = manifest.dumps(sample(audio=True))
    assert "mic" not in text and "audio_mode" not in text
    text = manifest.dumps(sample(audio=True, mic=True, audio_mode="pulse"))
    assert "mic = true" in text and 'audio_mode = "pulse"' in text
    p = manifest.loads(text).permissions
    assert (p.audio, p.mic, p.audio_mode) == (True, True, "pulse")


def test_mic_needs_audio():
    with pytest.raises(ManifestError, match="mic needs audio"):
        manifest.loads(manifest.dumps(sample(audio=True, mic=True)).replace("audio = true", "audio = false"))


def test_the_audio_mode_must_be_known():
    with pytest.raises(ManifestError, match="audio_mode must be one of pipewire, pulse"):
        manifest.loads(manifest.dumps(sample(audio=True)).replace("audio = true", 'audio = true\naudio_mode = "alsa"'))


def test_an_audio_mode_of_the_wrong_type_is_refused():
    with pytest.raises(ManifestError):
        manifest.loads(manifest.dumps(sample(audio=True)).replace("audio = true", "audio = true\naudio_mode = 3"))


# -- add ---------------------------------------------------------------------------------


def test_add_grants_neither_the_microphone_nor_a_special_mode(h):
    h.add(extra=["--allow", "audio"])
    p = saved()
    assert (p.audio, p.mic, p.audio_mode) == (True, False, "pipewire")


def test_allowing_mic_at_add_implies_audio(h):
    h.add(extra=["--allow", "mic"])
    p = saved()
    assert (p.audio, p.mic) == (True, True)


def test_add_with_pulse_mode(h):
    h.add(extra=["--allow", "audio", "--audio-mode", "pulse"])
    assert saved().audio_mode == "pulse"


# -- perms -------------------------------------------------------------------------------


def test_perms_allow_mic_implies_audio_and_warns(h):
    h.add()
    c = perms(h, "--allow", "mic")
    assert (saved().audio, saved().mic) == (True, True)
    assert "grants access to the microphone" in c.text


def test_perms_deny_audio_takes_the_microphone_with_it(h):
    h.add(extra=["--allow", "mic"])
    perms(h, "--deny", "audio")
    assert (saved().audio, saved().mic) == (False, False)


def test_perms_deny_mic_keeps_playback(h):
    h.add(extra=["--allow", "mic"])
    perms(h, "--deny", "mic")
    assert (saved().audio, saved().mic) == (True, False)


def test_perms_changes_the_mode_and_shows_it(h):
    h.add(extra=["--allow", "audio"])
    c = perms(h, "--audio-mode", "pulse")
    assert saved().audio_mode == "pulse"
    assert "audio-mode" in c.text and "pipewire" in c.text and "pulse" in c.text


def test_pulse_mode_warns_that_the_microphone_cannot_be_denied(h):
    h.add(extra=["--allow", "audio"])
    c = perms(h, "--audio-mode", "pulse")
    assert "which also lets the app record from the microphone" in c.text


def test_pulse_mode_does_not_warn_when_the_microphone_is_granted_anyway(h):
    h.add(extra=["--allow", "mic"])
    c = perms(h, "--audio-mode", "pulse")
    assert "cannot be denied" not in c.text


def test_the_mode_is_shown_only_with_audio(h):
    h.add()
    assert "audio-mode" not in perms(h).text
    perms(h, "--allow", "audio")
    assert "audio-mode" in perms(h).text


def test_the_review_lists_mic_among_the_flags(h):
    h.add(extra=["--allow", "mic"])
    assert "mic" in permission_lines_text(saved())
