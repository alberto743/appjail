# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The private audio graph against a real PipeWire, WirePlumber and pipewire-pulse (guest only).

The host side is a private stack with a test microphone (a tone), a second microphone, a speaker (a null sink) and a camera
stand-in. The app side is the real appjail graph (audiojail.PrivateAudio) and a real app jail. Besides what the graph does,
the tests record what it does not do: the limits listed in DECISIONS.md.
"""

import json
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from appjail import audiojail, jail, runner, runtimejail, seccomp
from appjail.manifest import Manifest, Permissions

from .helpers import NO_RESTRICTION, build, integration, wait_for

HOST_CONF = """context.spa-libs = { videotestsrc = videotestsrc/libspa-videotestsrc, audiotestsrc = audiotestsrc/libspa-audiotestsrc }
context.objects = [
  { factory = adapter args = { factory.name = videotestsrc node.name = host-camera media.class = Video/Source media.type = Video media.role = Camera } }
  { factory = adapter args = { factory.name = audiotestsrc node.name = host-mic media.class = Audio/Source } }
  { factory = adapter args = { factory.name = audiotestsrc node.name = host-mic2 media.class = Audio/Source } }
  { factory = adapter args = { factory.name = support.null-audio-sink node.name = host-speaker media.class = Audio/Sink object.linked = true } }
]
"""
TONE = ("import math, struct, wave; w = wave.open('/home/app/tone.wav', 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000); "
        "w.writeframes(b''.join(struct.pack('<h', int(12000 * math.sin(2 * math.pi * 440 * i / 48000))) for i in range(48000 * 3))); w.close()")


class Host:
    """The host's audio: a private PipeWire stack standing in for the user's desktop."""

    def __init__(self, base):
        self.base = base
        self.rt = base / "host"
        self.rt.mkdir(mode=0o700)
        cfg = base / "hostcfg" / "pipewire" / "pipewire.conf.d"
        cfg.mkdir(parents=True)
        (cfg / "x.conf").write_text(HOST_CONF)
        self.env = {"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(self.rt), "XDG_CONFIG_HOME": str(base / "hostcfg"), "HOME": str(base)}
        self.procs = []

    @property
    def pulse(self):
        return f"unix:{self.rt}/pulse/native"

    def start(self, cmd):
        proc = subprocess.Popen([cmd], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(proc)
        return proc

    def nodes(self):
        out = subprocess.run(["pw-dump"], env=self.env, capture_output=True, text=True, timeout=10).stdout
        try:
            return {o["info"]["props"].get("node.name"): o["id"] for o in json.loads(out) if o.get("type", "").endswith("Node")}
        except (ValueError, KeyError, TypeError):
            return {}

    def pactl(self, *args):
        return subprocess.run(["pactl", "-s", self.pulse, *args], env=self.env, check=True, capture_output=True, text=True).stdout

    def set_default(self, kind, name, timeout=10):
        """Make a device the default (kind: sink or source). A device that was only just loaded is not known to the session
        manager at once: pactl answers "Not supported" until it is, so ask again."""
        deadline = time.monotonic() + timeout
        while True:
            done = subprocess.run(["pactl", "-s", self.pulse, f"set-default-{kind}", name], env=self.env, capture_output=True, text=True)
            if done.returncode == 0:
                return
            if time.monotonic() > deadline:
                raise AssertionError(f"set-default-{kind} {name}: {done.stderr.strip()}")
            time.sleep(0.2)

    def links(self):
        """The host nodes the app's tunnels are linked to: (sources feeding the tunnel, sinks the tunnel feeds)."""
        sources, sinks, current = set(), set(), ""
        for line in subprocess.run(["pw-link", "-l"], env=self.env, capture_output=True, text=True).stdout.splitlines():
            if not line.startswith(" "):
                current = line.strip()
                continue
            other = line.strip()[3:].split(":")[0].strip()
            if current.startswith("PipeWire:input") and line.strip().startswith("|<-"):
                sources.add(other)
            elif current.startswith("PipeWire:output") and line.strip().startswith("|->"):
                sinks.add(other)
        return sorted(sources), sorted(sinks)

    def streams(self, kind):
        """(device name, stream name) of every recording ('source-output') or playback ('sink-input') stream on the host."""
        device_kind = "sources" if kind == "source-output" else "sinks"
        index = {}
        for line in self.pactl("list", "short", device_kind).splitlines():
            fields = line.split("\t")
            index[fields[0]] = fields[1]
        out, block = [], {}
        for line in self.pactl("list", f"{kind}s").splitlines():
            line = line.strip()
            if line.lower().startswith(kind.replace("-", " ") + " #"):
                block = {}
                out.append(block)
            elif line.startswith(("Source:", "Sink:")):
                block["device"] = index.get(line.split(":", 1)[1].strip(), "?")
            elif line.startswith("media.name"):
                block["stream"] = line.split("=", 1)[1].strip(' "')
        return out


@pytest.fixture
def host():
    for tool in (*audiojail.TOOLS, "pw-record", "pw-link", "pactl", "parec", "paplay", "pw-cat"):
        if not shutil.which(tool):
            pytest.skip(f"needs {tool} (tests/vm/packages.txt)")
    base = Path(tempfile.mkdtemp(prefix="pa"))
    h = Host(base)
    try:
        h.start("pipewire")
        assert wait_for(lambda: (h.rt / "pipewire-0").is_socket(), 10)
        h.start("wireplumber")
        assert wait_for(lambda: "host-mic" in h.nodes(), 10)
        h.start("pipewire-pulse")
        assert wait_for(lambda: (h.rt / "pulse" / "native").is_socket(), 10)
        yield h
    finally:
        for p in reversed(h.procs):
            p.terminate()
        for p in h.procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        shutil.rmtree(base, ignore_errors=True)


def private(host, mic=True, name="notes-app"):
    return audiojail.PrivateAudio(name, mic, host.rt / "pulse" / "native", host.rt, os.getuid(), os.getgid())


def in_jail(sandbox, audio, command):
    """Run a command in an app jail whose audio is this private graph."""
    (sandbox / "rt").mkdir(exist_ok=True)
    kw = build(sandbox, sandbox / "rt", audio=True, display="none")
    kw["command"] = command
    fd = seccomp.open_fd(False)
    try:
        args = runtimejail.runtime_args(**kw, audio_sockets=(audio.pipewire_socket, audio.pulse_socket), seccomp_fd=fd)
        return jail.supervise([jail.find_bwrap(), *args], timeout=60, pass_fds=(fd,), keep=1 << 20)
    finally:
        os.close(fd)


def peak(data):
    """Largest absolute sample of a 16-bit little-endian WAV (header skipped); 0 when there is nothing."""
    body = data[44:]
    n = len(body) // 2
    return max((abs(x) for x in struct.unpack(f"<{n}h", body[:n * 2])), default=0)


def node_names(proc):
    try:
        return sorted(o["info"]["props"]["node.name"] for o in json.loads(proc.stdout) if o.get("type", "").endswith("Node"))
    except (ValueError, KeyError, TypeError):
        return []


def record(sandbox, audio, target="app-mic", seconds=3):
    path = sandbox / "home" / "rec.wav"
    path.unlink(missing_ok=True)
    in_jail(sandbox, audio, ["/usr/bin/timeout", "-s", "INT", str(seconds), "/usr/bin/pw-record", "--target", target, "/home/app/rec.wav"])
    return path.read_bytes() if path.exists() else b""


# -- what the app sees and gets --------------------------------------------------------------


@integration
def test_the_app_sees_only_the_tunnels_and_records_the_host_microphone(sandbox, host):
    with private(host) as audio:
        seen = node_names(in_jail(sandbox, audio, ["/usr/bin/pw-dump"]))
        assert {"app-speaker", "app-mic"} <= set(seen)
        assert not [n for n in seen if n.startswith("host-") or "v4l2" in n], seen  # no host device, no camera
        assert peak(record(sandbox, audio)) > 1000  # the host microphone's tone


@integration
def test_without_mic_there_is_no_source_and_only_silence(sandbox, host):
    with private(host, mic=False) as audio:
        seen = node_names(in_jail(sandbox, audio, ["/usr/bin/pw-dump"]))
        assert "app-speaker" in seen and "app-mic" not in seen and not [n for n in seen if n.startswith("host-")]
        # pw-record falls back to the default source, which is the private sink's monitor: silence, never the host microphone
        assert peak(record(sandbox, audio)) == 0


@integration
def test_a_pulse_only_app_sees_the_tunnels_too(sandbox, host):
    with private(host) as audio:
        assert "PipeWire" in in_jail(sandbox, audio, ["/usr/bin/pactl", "info"]).stdout
        sources = in_jail(sandbox, audio, ["/usr/bin/pactl", "list", "short", "sources"]).stdout
        assert "app-mic" in sources and "host-" not in sources
        path = sandbox / "home" / "p.wav"
        in_jail(sandbox, audio, ["/usr/bin/timeout", "-s", "INT", "4", "/usr/bin/parec", "--device=app-mic", "--file-format=wav", "/home/app/p.wav"])
        assert peak(path.read_bytes()) > 1000


@integration
@pytest.mark.parametrize("native", [False, True], ids=["pulse-client", "pipewire-client"])
def test_playback_reaches_the_host_speaker(sandbox, host, native):
    with private(host, mic=False) as audio:
        assert in_jail(sandbox, audio, ["/usr/bin/python3", "-c", TONE]).returncode == 0
        out = sandbox / "host.wav"
        rec = subprocess.Popen(["timeout", "6", "parec", "-s", host.pulse, "-d", "host-speaker.monitor", "--file-format=wav", str(out)],
                               env=host.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        play = ["/usr/bin/pw-cat", "--playback", "/home/app/tone.wav"] if native else ["/usr/bin/paplay", "/home/app/tone.wav"]
        assert in_jail(sandbox, audio, play).returncode == 0
        rec.wait(10)
        assert peak(out.read_bytes()) > 3000


@integration
def test_no_camera_is_ever_in_the_graph_even_with_one_on_the_host(sandbox, host):
    if not Path("/sys/class/video4linux/video0").exists():
        pytest.skip("needs a video device (the vivid module)")
    with private(host) as audio:
        assert not [n for n in node_names(in_jail(sandbox, audio, ["/usr/bin/pw-dump"])) if "v4l2" in n or "camera" in n]


@integration
def test_a_stray_node_makes_the_graph_unusable(host, monkeypatch):
    stray = ('context.spa-libs = { videotestsrc = videotestsrc/libspa-videotestsrc }\ncontext.objects = [ { factory = adapter args = '
             '{ factory.name = videotestsrc node.name = stray-camera media.class = Video/Source media.type = Video } } ]\n')
    real = audiojail.pipewire_conf
    monkeypatch.setattr(audiojail, "pipewire_conf", lambda mic: real(mic) + stray)
    with pytest.raises(audiojail.AudioUnavailable, match="stray-camera"), private(host):
        pytest.fail("a graph with a stray node must not be handed to an app")


# -- the daemons -------------------------------------------------------------------------------


def descendants(pid):
    kids = {}
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                ppid = int(re.search(r"^PPid:\s+(\d+)", (p / "status").read_text(), re.MULTILINE).group(1))
            except (OSError, AttributeError):
                continue
            kids.setdefault(ppid, []).append(int(p.name))
    out, todo = [], [pid]
    while todo:
        for k in kids.get(todo.pop(), []):
            out.append(k)
            todo.append(k)
    return out


def rss_kib(pid):
    try:
        return int(re.search(r"^VmRSS:\s+(\d+)", Path(f"/proc/{pid}/status").read_text(), re.MULTILINE).group(1))
    except (OSError, AttributeError):
        return 0


@integration
def test_the_daemons_are_jailed_and_nothing_outlives_the_graph(host):
    with private(host) as audio:
        kids = descendants(audio.proc.pid)
        names = {Path(f"/proc/{k}/comm").read_text().strip() for k in kids if Path(f"/proc/{k}/comm").exists()}
        assert {"pipewire", "wireplumber", "pipewire-pulse"} <= names
        assert sum(rss_kib(k) for k in kids) < 200 * 1024  # about 36 MiB measured
        base = audio.base
    assert wait_for(lambda: not any(Path(f"/proc/{k}").exists() for k in kids), 5)
    assert not base.exists()


@integration
def test_killing_the_jail_takes_every_daemon_with_it(host):
    with private(host) as audio:
        kids = descendants(audio.proc.pid)
        audio.proc.kill()
        assert wait_for(lambda: not any(Path(f"/proc/{k}").exists() for k in kids), 5), "daemons outlived the jail"
        s = socket.socket(socket.AF_UNIX)
        with pytest.raises(OSError):
            s.connect(str(audio.pipewire_socket))  # the socket file stays, but nobody answers


@integration
def test_the_host_sees_a_stream_named_after_the_app(host):
    with private(host):
        assert wait_for(lambda: host.streams("source-output"), 8)
        stream = host.streams("source-output")[0]["stream"]
        assert stream.startswith("Tunnel for ") and stream.endswith("@notes-app"), stream


# -- limits (DECISIONS.md): what the graph does not do ---------------------------------------


@integration
def test_the_tunnel_uses_the_default_source_at_connection_time(host):
    host.set_default("source", "host-mic2")
    with private(host):
        assert wait_for(lambda: any(s.get("device") == "host-mic2" for s in host.streams("source-output")), 8), host.streams("source-output")


@integration
def test_a_default_change_adds_links_and_unplug_removes_only_the_unplugged_ones(host):
    """Measured on the real graph (pactl shows only one source per stream and hides this). A headset that becomes the default
    is ADDED to the tunnel's links (playback on both, the microphone mixed from both) instead of replacing them; unplugging
    removes only its own links; nothing re-attaches by itself."""
    def stable(expected):
        return wait_for(lambda: host.links() == expected, 6)

    with private(host):
        assert wait_for(lambda: all(host.links()), 8)
        assert host.links() == (["host-mic"], ["host-speaker"])
        host.pactl("load-module", "module-null-sink", "sink_name=headset")
        time.sleep(2)
        assert host.links() == (["host-mic"], ["host-speaker"])  # plugged, not the default: nothing happens
        host.set_default("sink", "headset")
        host.set_default("source", "headset.monitor")
        assert stable((["headset", "host-mic"], ["headset", "host-speaker"]))  # added, not moved
        index = next(line.split("\t")[0] for line in host.pactl("list", "short", "modules").splitlines() if "sink_name=headset" in line)
        host.pactl("unload-module", index)
        assert stable((["host-mic"], ["host-speaker"]))  # the unplugged device's links are gone
        host.pactl("load-module", "module-null-sink", "sink_name=headset")
        time.sleep(3)
        assert host.links() == (["host-mic"], ["host-speaker"])  # and nothing re-attaches by itself


@integration
def test_a_tunnel_on_a_headset_that_is_unplugged_goes_silent_for_good(sandbox, host):
    host.pactl("load-module", "module-null-sink", "sink_name=headset")
    host.set_default("sink", "headset")
    host.set_default("source", "headset.monitor")
    with private(host) as audio:
        assert wait_for(lambda: host.links() == (["headset"], ["headset"]), 8), host.links()
        index = next(line.split("\t")[0] for line in host.pactl("list", "short", "modules").splitlines() if "sink_name=headset" in line)
        host.pactl("unload-module", index)
        time.sleep(3)
        assert host.links() == ([], [])  # attached to nothing, and the app is not told: its graph is unchanged
        assert {"app-speaker", "app-mic"} <= set(node_names(in_jail(sandbox, audio, ["/usr/bin/pw-dump"])))
        host.pactl("load-module", "module-null-sink", "sink_name=headset")
        time.sleep(3)
        assert host.links() == ([], [])


@integration
def test_the_tunnel_does_not_reconnect_after_the_hosts_pulse_server_restarts(host):
    with private(host):
        assert wait_for(lambda: any(s.get("device") == "host-mic" for s in host.streams("source-output")), 8)
        old = next(p for p in host.procs if Path(f"/proc/{p.pid}/comm").read_text().strip() == "pipewire-pulse")
        old.terminate()
        old.wait(10)
        host.start("pipewire-pulse")
        assert wait_for(lambda: (host.rt / "pulse" / "native").is_socket(), 10)
        assert not wait_for(lambda: any(s.get("device") == "host-mic" for s in host.streams("source-output")), 10)  # the app's audio stays down


# -- a whole launch ---------------------------------------------------------------------------


@integration
def test_launch_runs_the_app_on_its_private_graph(sandbox, host, monkeypatch):
    perms = {"audio": True, "mic": True, "display": "none"}
    kw = build(sandbox, sandbox / "rt", **perms)
    (sandbox / "rt").mkdir(exist_ok=True)
    (kw["root"] / "AppRun").write_text(
        "#!/bin/sh\n/usr/bin/timeout -s INT 3 /usr/bin/pw-record --target app-mic /home/app/m.wav\n"
        "/usr/bin/pw-dump | /usr/bin/python3 -c \"import json,sys; print(sorted(o['info']['props']['node.name'] for o in json.load(sys.stdin) "
        "if o['type'].endswith('Node')))\" > /home/app/nodes.txt\n")
    (kw["root"] / "AppRun").chmod(0o755)
    m = Manifest("app", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage", permissions=Permissions(**perms))
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: (m, kw["root"], kw["home"], kw["etc_dir"]))
    said = []
    code = runner.launch("app", host_env=dict(host.env), say=said.append, warn=said.append, restricted=NO_RESTRICTION)
    assert code == 0, "\n".join(said)
    assert not [line for line in said if "audio_mode" in line], said  # no fallback
    assert peak((kw["home"] / "m.wav").read_bytes()) > 1000
    assert "app-mic" in (kw["home"] / "nodes.txt").read_text() and "host-" not in (kw["home"] / "nodes.txt").read_text()
    assert not list(host.rt.glob("appjail-audio-*"))  # the graph is gone with the run
