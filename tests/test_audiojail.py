# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The private audio graph without a PipeWire: configuration, jail arguments, availability, the resolver and the runner's use of it."""

import json
import socket
import subprocess
from typing import ClassVar

import pytest

from appjail import audiojail, audiomode, jail, runner, store
from appjail.errors import JailError
from appjail.manifest import Permissions

from .helpers import NO_RESTRICTION, Extractor, install, pairs


def have(*tools):
    return lambda name: f"/usr/bin/{name}" if name in tools else None


ALL = ("pipewire", "wireplumber", "pipewire-pulse", "pw-dump")


@pytest.fixture
def pulse_socket(tmp_path):
    path = tmp_path / "native"
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    yield str(path)
    s.close()


@pytest.fixture
def module_dir(tmp_path):
    d = tmp_path / "mods"
    d.mkdir()
    (d / "libpipewire-module-pulse-tunnel.so").write_text("")
    return str(d)


# -- availability ---------------------------------------------------------------------------


def test_available_when_everything_is_there(pulse_socket, module_dir):
    assert audiojail.availability(pulse_socket, have(*ALL), [module_dir]) == (True, "")


@pytest.mark.parametrize("missing", ALL)
def test_each_missing_tool_has_its_own_reason(missing, pulse_socket, module_dir):
    ok, why = audiojail.availability(pulse_socket, have(*[t for t in ALL if t != missing]), [module_dir])
    assert not ok and missing in why


def test_a_tool_outside_the_system_directories_is_not_usable(pulse_socket, module_dir):
    ok, why = audiojail.availability(pulse_socket, lambda name: f"/opt/pw/bin/{name}", [module_dir])
    assert not ok and "/usr" in why


def test_the_tunnel_module_and_the_host_pulse_socket_are_needed(tmp_path, pulse_socket, module_dir):
    assert "pulse-tunnel" in audiojail.availability(pulse_socket, have(*ALL), [str(tmp_path)])[1]
    assert "Pulse socket" in audiojail.availability(str(tmp_path / "none"), have(*ALL), [module_dir])[1]
    assert "Pulse socket" in audiojail.availability(None, have(*ALL), [module_dir])[1]


# -- configuration and jail ----------------------------------------------------------------


def test_the_graph_has_a_sink_and_a_source_only_with_mic():
    assert "tunnel.mode = sink" in audiojail.pipewire_conf(False) and "tunnel.mode = source" not in audiojail.pipewire_conf(False)
    both = audiojail.pipewire_conf(True)
    assert "tunnel.mode = sink" in both and "tunnel.mode = source" in both
    assert f"unix:{audiojail.HOST_PULSE}" in both and "pulse.device" not in both  # the host's defaults at connection time


def test_wireplumber_has_no_hardware_monitors():
    for monitor in ("audio", "video-capture", "bluetooth"):
        assert f"hardware.{monitor} = disabled" in audiojail.WIREPLUMBER_CONF


@pytest.mark.parametrize("name, host", [("lagrange", "lagrange"), ("My_App.v2", "my-app-v2"), ("a" * 80, "a" * 63), ("..", "app")])
def test_the_hostname_carries_the_app_name(name, host):
    assert audiojail.hostname_for(name) == host


def test_the_daemons_jail_has_no_network_and_only_what_it_needs(tmp_path):
    args = audiojail.daemon_args(tmp_path / "rt", tmp_path / "cfg", tmp_path / "passwd", tmp_path / "native", ["/bin/true"], "notes")
    assert "--unshare-all" in args and "--share-net" not in args and "--die-with-parent" in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert args[args.index("--hostname") + 1] == "notes"
    assert (str(tmp_path / "rt"), audiojail.RUNTIME) in pairs(args, "--bind")
    assert {dest for _, dest in pairs(args, "--ro-bind")} >= {audiojail.CONFIG, "/etc/passwd", audiojail.HOST_PULSE}
    assert args[-1] == "/bin/true" and args[args.index("--remount-ro") + 1] == "/"


# -- reading the graph ---------------------------------------------------------------------


def dump(nodes, wireplumber=True):
    objects = [{"type": "PipeWire:Interface:Node", "info": {"props": {"node.name": n}}} for n in nodes]
    if wireplumber:
        objects.append({"type": "PipeWire:Interface:Client", "info": {"props": {"application.name": "WirePlumber"}}})
    return json.dumps(objects)


def test_graph_nodes_are_read_from_a_dump():
    assert audiojail.graph_nodes(dump(["app-speaker", "Dummy-Driver"])) == (["app-speaker", "Dummy-Driver"], True)
    assert audiojail.graph_nodes(dump(["x"], wireplumber=False)) == (["x"], False)
    for junk in ("", "not json", "[1, 2]", '{"a": 1}'):
        assert audiojail.graph_nodes(junk) == ([], False)


def test_only_the_expected_nodes_are_allowed():
    assert audiojail.unexpected(["Dummy-Driver", "Freewheel-Driver", "app-speaker"], mic=False) == []
    assert audiojail.unexpected(["app-speaker", "app-mic"], mic=True) == []
    assert audiojail.unexpected(["app-speaker", "app-mic"], mic=False) == ["app-mic"]
    assert audiojail.unexpected(["app-speaker", "v4l2_input.platform-x.0"], mic=True) == ["v4l2_input.platform-x.0"]


def test_daemons_that_exit_are_unavailable_and_leave_nothing(tmp_path, monkeypatch):
    audio = audiojail.PrivateAudio("app", False, "/nonexistent", tmp_path, 1000, 1000, timeout=5)
    monkeypatch.setattr(audio, "_jail_argv", lambda command, config, passwd: ["/bin/true"])
    with pytest.raises(audiojail.AudioUnavailable, match="exited"), audio:
        pytest.fail("must not get here")
    assert list(tmp_path.iterdir()) == []


# -- start-up against a fake graph --------------------------------------------------------


class Sock:
    def is_socket(self):
        return True


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """A PrivateAudio whose daemons are `sleep` and whose look at the graph (pw-dump in a jail) is a script of answers."""
    audio = audiojail.PrivateAudio("app", False, "/x", tmp_path, 1000, 1000, timeout=2)
    monkeypatch.setattr(audio, "_write_config", lambda: (tmp_path, tmp_path))
    monkeypatch.setattr(audio, "_jail_argv", lambda *a: ["sh", "-c", "echo daemon-says-boom >&2; sleep 30"])
    monkeypatch.setattr(audiojail.PrivateAudio, "pipewire_socket", property(lambda self: Sock()))
    monkeypatch.setattr(audiojail.PrivateAudio, "pulse_socket", property(lambda self: Sock()))
    monkeypatch.setattr(audiojail, "SETTLE", 0)
    answers = []

    def supervise(argv, **kw):
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, Exception):
            raise answer
        return subprocess.CompletedProcess(argv, 0, answer, "")

    monkeypatch.setattr(jail, "supervise", supervise)
    audio.answers = answers
    return audio


GOOD = dump(["Dummy-Driver", "Freewheel-Driver", "app-speaker"])


def test_a_clean_graph_is_accepted(fake):
    fake.answers.append(GOOD)
    with fake as audio:
        assert audio is fake


def test_a_look_that_times_out_is_not_ready_yet_and_not_an_exception(fake):
    fake.answers.append(JailError("jailed command aborted: timed out"))
    with pytest.raises(audiojail.AudioUnavailable, match="did not come up in time") as failure, fake:
        pytest.fail("must not get here")
    assert "the daemons said: daemon-says-boom" in str(failure.value)  # and the reason is in the message
    assert list(fake.base.parent.glob("appjail-audio-*")) == []


def test_the_graph_comes_up_after_a_slow_first_look(fake):
    fake.answers.extend([JailError("jailed command aborted: timed out"), GOOD])
    with fake:
        pass


def test_an_unreadable_final_look_is_not_a_clean_one(fake):
    fake.answers.extend([GOOD, "not json"])  # ready, then nothing can be read at the check
    with pytest.raises(audiojail.AudioUnavailable, match="could not be checked"), fake:
        pytest.fail("a graph that was not checked must not be handed to an app")


def test_a_stray_node_at_the_final_look_is_refused(fake):
    fake.answers.extend([GOOD, dump(["app-speaker", "v4l2_input.platform-x.0"])])
    with pytest.raises(audiojail.AudioUnavailable, match="v4l2_input"), fake:
        pytest.fail("must not get here")


# -- the resolver --------------------------------------------------------------------------


def test_no_audio_means_no_backend_and_no_note():
    assert audiomode.resolve(Permissions(), {}) == (None, None)


def test_pulse_mode_is_the_pulse_socket_without_a_note():
    assert audiomode.resolve(Permissions(audio=True, audio_mode="pulse"), {}) == ("pulse", None)


def test_pipewire_mode_is_used_when_it_is_available(pulse_socket):
    env = {"XDG_RUNTIME_DIR": str(socket_dir(pulse_socket))}
    assert audiomode.resolve(Permissions(audio=True), env, availability=lambda s: (True, "")) == ("pipewire", None)


def socket_dir(pulse_socket):
    """A runtime directory whose pulse/native is the given socket."""
    from pathlib import Path
    rt = Path(pulse_socket).parent / "rt"
    (rt / "pulse").mkdir(parents=True, exist_ok=True)
    link = rt / "pulse" / "native"
    if not link.exists():
        link.symlink_to(pulse_socket)
    return rt


def unavailable(perms, env):
    return audiomode.resolve(perms, env, availability=lambda s: (False, "wireplumber is not installed"))


def test_without_mic_a_graph_that_is_not_available_means_no_audio_even_with_a_pulse_socket(pulse_socket):
    backend, note = unavailable(Permissions(audio=True), {"XDG_RUNTIME_DIR": str(socket_dir(pulse_socket))})
    assert backend is None and "wireplumber is not installed" in note and "no audio" in note and "not granted" in note


def test_with_mic_a_graph_that_is_not_available_falls_back_to_the_pulse_socket_and_warns(pulse_socket):
    backend, note = unavailable(Permissions(audio=True, mic=True), {"XDG_RUNTIME_DIR": str(socket_dir(pulse_socket))})
    assert backend == "pulse" and "wireplumber is not installed" in note and "record from the microphone" in note


def test_with_mic_and_no_host_socket_there_is_no_audio():
    backend, note = unavailable(Permissions(audio=True, mic=True), {"XDG_RUNTIME_DIR": "/nonexistent"})
    assert backend is None and "no Pulse socket" in note and "no audio" in note


@pytest.mark.parametrize("mic, has_pulse, backend", [(False, True, None), (False, False, None), (True, True, "pulse"), (True, False, None)])
def test_fallback_backend(mic, has_pulse, backend):
    assert audiomode.fallback(Permissions(audio=True, mic=mic), "x", has_pulse)[0] == backend


# -- the runner ----------------------------------------------------------------------------


class FakeAudio:
    started: ClassVar[list] = []

    def __init__(self, name, mic, host_pulse, host_runtime_dir, uid, gid):
        self.args = (name, mic, host_pulse)
        self.pipewire_socket, self.pulse_socket = store.data_dir() / "pw", store.data_dir() / "pulse"

    def __enter__(self):
        FakeAudio.started.append(self.args)
        return self

    def __exit__(self, *exc):
        FakeAudio.started.append("closed")


def launch(sandbox, runtime, perms, monkeypatch, said=None, **patches):
    install(sandbox, **perms)
    captured = []
    runner.launch("app", [], host_env={"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"}, extract=Extractor(),
                  say=lambda *_: None, warn=(said if said is not None else []).append, runner=lambda argv: captured.append(argv) or 0,
                  restricted=NO_RESTRICTION)
    return captured[0]


def test_the_app_gets_its_private_sockets_and_not_the_hosts(sandbox, runtime, monkeypatch):
    FakeAudio.started = []
    monkeypatch.setattr(audiojail, "PrivateAudio", FakeAudio)
    monkeypatch.setattr(audiomode, "resolve", lambda perms, env: ("pipewire", None))
    monkeypatch.setattr(audiomode, "host_pulse", lambda env: "/host/pulse")
    argv = launch(sandbox, runtime, {"audio": True, "mic": True, "display": "none"}, monkeypatch)
    rt = f"/run/user/{__import__('os').getuid()}"
    binds = pairs(argv, "--ro-bind")
    assert (str(store.data_dir() / "pw"), f"{rt}/pipewire-0") in binds and (str(store.data_dir() / "pulse"), f"{rt}/pulse/native") in binds
    assert FakeAudio.started == [("app", True, "/host/pulse"), "closed"]  # mic is passed on; the graph is closed with the run
    assert "PULSE_SERVER" in argv and f"unix:{rt}/pulse/native" in argv


class Broken(FakeAudio):
    def __enter__(self):
        raise audiojail.AudioUnavailable("the private audio daemons exited")


def host_pulse_bind(argv, runtime):
    return (str(runtime / "pulse" / "native"), f"/run/user/{__import__('os').getuid()}/pulse/native") in pairs(argv, "--ro-bind")


def test_a_graph_that_cannot_start_falls_back_to_the_pulse_socket_for_an_app_with_mic(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(audiojail, "PrivateAudio", Broken)
    monkeypatch.setattr(audiomode, "resolve", lambda perms, env: ("pipewire", None))
    said = []
    argv = launch(sandbox, runtime, {"audio": True, "mic": True, "display": "none"}, monkeypatch, said)
    assert any("the private audio daemons exited" in line and "Pulse socket" in line for line in said)
    assert host_pulse_bind(argv, runtime) and "PULSE_SERVER" in argv


def test_a_graph_that_cannot_start_leaves_an_app_without_mic_with_no_audio_socket(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(audiojail, "PrivateAudio", Broken)
    monkeypatch.setattr(audiomode, "resolve", lambda perms, env: ("pipewire", None))
    said = []
    argv = launch(sandbox, runtime, {"audio": True, "display": "none"}, monkeypatch, said)
    assert any("the private audio daemons exited" in line and "no audio" in line for line in said)
    assert not host_pulse_bind(argv, runtime)
    assert "PULSE_SERVER" not in argv and not any("pulse" in str(a) or "pipewire" in str(a) for a in argv)


def test_no_graph_and_no_host_audio_binds_nothing(sandbox, runtime):
    from appjail import runtimejail
    env = {}
    assert runtimejail._audio_args(str(runtime), "/run/user/1000", env, None, host_audio=False) == [] and not env
    assert runtimejail._audio_args(str(runtime), "/run/user/1000", env, None) != [] and "PULSE_SERVER" in env  # the default is unchanged


@pytest.mark.parametrize("perms, noisy", [({}, False), ({"audio": True, "audio_mode": "pulse"}, False), ({"audio": True}, True), ({"audio": True, "mic": True}, True)])
def test_launch_tells_only_when_the_requested_mode_is_not_what_it_gets(sandbox, runtime, monkeypatch, perms, noisy):
    monkeypatch.setattr(audiojail, "availability", lambda host_pulse: (False, "wireplumber is not installed"))
    said = []
    launch(sandbox, runtime, {**perms, "display": "none"}, monkeypatch, said)
    assert any("audio_mode pipewire is not available" in line for line in said) is noisy
