# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Menu entries: generated from sanitised fields only, optional file types, icons, lifecycle."""

import os
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from appjail import cli, desktop, store
from appjail.cmd_desktop import refresh_after_update

from .helpers import Script

ARGV = ["/opt/appjail/bin/appjail"]


def png(size=64):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", size, size) + b"\x08\x06\x00\x00\x00" + b"\0\0\0\0"


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgconf"))
    monkeypatch.setattr(desktop, "launcher_argv", lambda: ARGV)
    return tmp_path / "xdg"


def extractor(desktop_text=None, icon=None, icon_name="myicon"):
    def extract(image, dest, fallback=False):
        dest = Path(dest)
        (dest / "usr").mkdir(parents=True)
        (dest / "AppRun").write_text("#!/bin/sh\n")
        if desktop_text is not None:
            (dest / "app.desktop").write_text(desktop_text)
        if icon is not None:
            (dest / f"{icon_name}.png").write_bytes(icon)
        return 2, 20
    return extract


DESKTOP = ("[Desktop Entry]\nName=My Viewer\nName[de]=Mein Betrachter\nComment=Views things\nExec=evil --steal %U\n"
           "TryExec=/bin/evil\nIcon=myicon\nCategories=Graphics;Viewer;\nMimeType=image/png;image/jpeg;x-scheme-handler/http;"
           "application/x-shellscript;text/plain;\n[Desktop Action x]\nExec=rm -rf ~\nName=X\n")


def added(h, **kw):
    h.add(extract=extractor(DESKTOP, png(), **kw))


def run(argv, console=None):
    console = console or Script()
    parsed = cli.build_parser().parse_args(argv)
    cli.cmd_desktop(parsed, console)
    return console


def test_mime_types_are_filtered():
    kept, ignored = desktop.split_mimes(
        "image/png;IMAGE/JPEG;x-scheme-handler/http;inode/directory;application/x-shellscript;text/x-python;"
        "image/png;bad type/x;a/b\nc;application/x-appimage;image/svg+xml;")
    assert kept == ["image/png", "image/svg+xml"]
    assert len(ignored) == 8 and "x-scheme-handler/http" in ignored


def test_at_most_32_types_are_kept():
    kept, ignored = desktop.split_mimes(";".join(f"application/x-t{i}" for i in range(40)))
    assert len(kept) == 32 and len(ignored) == 8


def test_only_display_fields_are_read_and_unlocalised():
    fields = desktop.parse_desktop(DESKTOP)
    assert set(fields) == {"Name", "Comment", "Icon", "Categories", "MimeType"}
    assert fields["Name"] == "My Viewer"


def test_entry_is_generated_not_copied():
    text = desktop.build_entry("viewer", desktop.parse_desktop(DESKTOP), argv=ARGV)
    assert "evil" not in text and "TryExec" not in text and "Desktop Action" not in text
    assert "Name=My Viewer (appjail)" in text and "X-Appjail-App=viewer" in text
    assert "Exec=/opt/appjail/bin/appjail run viewer\n" in text and "MimeType" not in text
    assert "Categories=Graphics;Viewer;" in text


def test_field_injection_is_neutralised():
    fields = {"Name": "Calc\nExec=evil\r\n[Desktop Action x]", "Comment": "hi\x1b[31m\nTerminal=true",
              "Categories": "Utility;\nExec=evil", "Icon": "../../x"}
    text = desktop.build_entry("calc", fields, argv=ARGV)
    lines = text.splitlines()
    assert sum(line.startswith("Exec=") for line in lines) == 1 and "Categories" not in text
    assert "Terminal=false" in lines and "Terminal=true" not in lines
    assert sum(line.startswith("[") for line in lines) == 1


def test_exec_quoting():
    assert desktop.exec_line("a", [], argv=["/p q/appjail"]) == '"/p q/appjail" run a'
    assert desktop.exec_line("a", [], argv=["/p$/100%/appjail"]) == '"/p\\$/100%%/appjail" run a'
    assert desktop.exec_line("a", ["image/png"], argv=ARGV) == "/opt/appjail/bin/appjail open a -- %F"
    assert desktop.exec_line("a", ["image/png"], rw=True, argv=ARGV) == "/opt/appjail/bin/appjail open a --rw -- %F"
    text = desktop.build_entry("a", {}, ["image/png"], argv=['/a\\b/appjail'])
    assert "Exec=\"/a\\\\\\\\b/appjail\" open a -- %F" in text  # quoted for the Exec value, then for the file format


@pytest.mark.skipif(not shutil.which("desktop-file-validate"), reason="desktop-file-utils not installed")
def test_generated_entries_validate(h, xdg, tmp_path):
    added(h)
    run(["desktop", "app", "--mime-all", "--yes"])
    proc = subprocess.run(["desktop-file-validate", str(desktop.entry_path("app"))], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_install_writes_entry_icon_and_nothing_else(h, xdg):
    added(h)
    out = run(["desktop", "app", "--mime", "image/png", "--yes"]).text
    entry = desktop.entry_path("app").read_text()
    assert "MimeType=image/png;" in entry and "open app -- %F" in entry and "Icon=appjail-app" in entry
    assert (xdg / "icons/hicolor/64x64/apps/appjail-app.png").read_bytes() == png()
    assert "not offered" in out.lower() and "x-scheme-handler/http" in out
    assert not (tmp := xdg.parent / "xdgconf" / "mimeapps.list").exists(), tmp


def test_without_selection_the_entry_is_a_launcher_only(h, xdg):
    added(h)
    run(["desktop", "app", "--yes"])
    assert "MimeType" not in desktop.entry_path("app").read_text()


def test_interactive_selection(h, xdg):
    added(h)
    run(["desktop", "app"], Script(["1,3", "y"]))
    assert "MimeType=image/png;text/plain;" in desktop.entry_path("app").read_text()


def test_the_type_prompt_states_the_mode_that_will_apply(h, xdg):
    added(h)
    assert "read-only)" in run(["desktop", "app"], Script(["1", "y"])).text
    run(["desktop", "app", "--remove"])
    text = run(["desktop", "app", "--rw"], Script(["1", "y"])).text
    assert "read-write; an app that saves by renaming a new file will fail)" in text and "read-only)" not in text


def test_undeclared_or_refused_types_are_rejected(h, xdg):
    added(h)
    for bad in ("x-scheme-handler/http", "audio/mpeg"):
        with pytest.raises(cli.Abort, match="not offered"):
            run(["desktop", "app", "--mime", bad, "--yes"])
    assert not desktop.entry_path("app").exists()


def test_show_lists_registered_offered_and_refused_types(h, xdg):
    added(h)
    before = run(["desktop", "app", "--show"]).text
    assert "app has no menu entry." in before and "Offered    : image/png, image/jpeg, text/plain" in before
    assert "Not offered: x-scheme-handler/http, application/x-shellscript" in before
    run(["desktop", "app", "--mime", "image/png", "--rw", "--yes"])
    after = run(["desktop", "app", "--show"]).text
    assert "Registered : image/png (read-write)" in after and "image/png *, image/jpeg, text/plain" in after
    assert desktop.installed_state("app") == (["image/png"], True)  # nothing was written


def test_show_excludes_the_writing_options(h, xdg):
    added(h)
    with pytest.raises(cli.Abort, match="--show"):
        run(["desktop", "app", "--show", "--mime", "image/png"])
    with pytest.raises(cli.Abort, match="--show"):
        run(["desktop", "--show", "--prune"])
    assert not desktop.entry_path("app").exists()


def test_rw_is_recorded_in_the_exec_and_kept_on_refresh(h, xdg):
    added(h)
    run(["desktop", "app", "--mime", "image/png", "--rw", "--yes"])
    assert desktop.installed_state("app") == (["image/png"], True)
    run(["desktop", "app", "--yes"])
    assert desktop.installed_state("app") == (["image/png"], True)


def test_icon_is_validated(h, xdg):
    h.add(extract=extractor(DESKTOP, png(4)))  # too small
    run(["desktop", "app", "--yes"])
    assert "Icon=" not in desktop.entry_path("app").read_text()
    assert desktop.icon_files("app") == []


def test_icon_symlink_cannot_leave_the_tree(h, xdg):
    def extract(image, dest, fallback=False):
        dest = Path(dest)
        dest.mkdir(parents=True)
        (dest / "AppRun").write_text("#!/bin/sh\n")
        (dest / "app.desktop").write_text("[Desktop Entry]\nName=X\nIcon=myicon\n")
        (dest / "myicon.png").symlink_to("/etc/passwd")
        (dest / ".DirIcon").symlink_to("../../etc/hostname")
        return 1, 1
    h.add(extract=extract)
    run(["desktop", "app", "--yes"])
    assert desktop.icon_files("app") == []


def test_svg_without_converter_gives_a_note_not_a_failure(h, xdg, monkeypatch):
    def extract(image, dest, fallback=False):
        dest = Path(dest)
        dest.mkdir(parents=True)
        (dest / "AppRun").write_text("#!/bin/sh\n")
        (dest / "app.desktop").write_text("[Desktop Entry]\nName=X\nIcon=logo\n")
        (dest / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
        return 1, 1
    h.add(extract=extract)
    monkeypatch.setattr(desktop, "RSVG", "/nonexistent/rsvg-convert")
    out = run(["desktop", "app", "--yes"]).text
    assert "rsvg-convert is not installed" in out and desktop.entry_path("app").is_file()
    assert "Icon=" not in desktop.entry_path("app").read_text()


def test_a_file_that_is_not_ours_is_never_overwritten_or_deleted(h, xdg):
    added(h)
    path = desktop.entry_path("app")
    path.parent.mkdir(parents=True)
    path.write_text("[Desktop Entry]\nName=Mine\n")
    with pytest.raises(cli.Abort, match="not touching"):
        run(["desktop", "app", "--yes"])
    run(["desktop", "app", "--remove"])
    assert path.read_text() == "[Desktop Entry]\nName=Mine\n"


def test_unknown_app_and_missing_name(h, xdg):
    with pytest.raises(cli.Abort, match="unknown app"):
        run(["desktop", "ghost", "--yes"])
    with pytest.raises(cli.Abort, match="--prune"):
        run(["desktop"])


def test_add_can_create_the_entry(h, xdg):
    console = h.add(extra=("--desktop", "--mime", "image/png"), extract=extractor(DESKTOP, png()))
    assert desktop.installed_state("app") == (["image/png"], False)
    assert "Entry" in console.text


def test_add_without_desktop_creates_none(h, xdg):
    added(h)
    assert not desktop.entry_path("app").exists()


def test_update_refresh_keeps_known_types_and_only_lists_new_ones(h, xdg):
    added(h)
    run(["desktop", "app", "--mime", "image/png", "--mime", "text/plain", "--yes"])
    (store.root_path("app") / "app.desktop").write_text(
        "[Desktop Entry]\nName=My Viewer 2\nIcon=myicon\nMimeType=image/png;image/gif;\n")
    console = Script()
    refresh_after_update("app", console)
    assert desktop.installed_state("app") == (["image/png"], False)
    assert "no longer offered by the app: text/plain" in console.text and "new file types offered: image/gif" in console.text


def test_svg_without_converter_is_explained_by_show_and_fixed_by_update(h, xdg, monkeypatch):
    def extract(image, dest, fallback=False):
        dest = Path(dest)
        dest.mkdir(parents=True)
        (dest / "AppRun").write_text("#!/bin/sh\n")
        (dest / "app.desktop").write_text("[Desktop Entry]\nName=X\nIcon=logo\n")
        (dest / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
        return 1, 1
    h.add(extract=extract)
    monkeypatch.setattr(desktop, "RSVG", "/nonexistent/rsvg-convert")
    run(["desktop", "app", "--yes"])
    console = Script()
    refresh_after_update("app", console)
    assert "rsvg-convert is not installed" in console.text
    assert "rsvg-convert missing" in run(["desktop", "app", "--show"]).text


def test_show_reports_the_installed_icon(h, xdg):
    added(h)
    run(["desktop", "app", "--yes"])
    assert "Icon       : 64x64 PNG" in run(["desktop", "app", "--show"]).text


def test_the_icon_cache_is_refreshed_with_the_gtk_tool(h, xdg, tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls"
    tool = bin_dir / "gtk-update-icon-cache"
    tool.write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    added(h)
    run(["desktop", "app", "--yes"])
    assert set(log.read_text().splitlines()) == {f"-q -t -f {xdg / 'icons/hicolor'}"}


def test_update_refresh_does_nothing_without_an_entry(h, xdg):
    added(h)
    refresh_after_update("app", Script())
    assert not desktop.entry_path("app").exists()


def test_remove_deletes_entry_and_icons(h, xdg):
    added(h)
    run(["desktop", "app", "--mime", "image/png", "--yes"])
    (xdg.parent / "xdgconf").mkdir()
    (xdg.parent / "xdgconf" / "mimeapps.list").write_text("[Default Applications]\nimage/png=appjail-app.desktop\n")
    console = Script()
    cli.cmd_remove(cli.build_parser().parse_args(["remove", "app", "--yes"]), console)
    assert not desktop.entry_path("app").exists() and desktop.icon_files("app") == []
    assert "mimeapps.list still names" in console.text


def test_prune_removes_entries_of_missing_apps_only(h, xdg):
    added(h)
    run(["desktop", "app", "--yes"])
    other = desktop.entry_path("gone")
    other.write_text("[Desktop Entry]\nName=Gone\nX-Appjail-App=gone\n")
    foreign = desktop.applications_dir() / "appjail-foreign.desktop"
    foreign.write_text("[Desktop Entry]\nName=Foreign\n")
    console = Script()
    cli.cmd_list(console)
    assert "missing app 'gone'" in console.text
    out = run(["desktop", "--prune"]).text
    assert "'gone'" in out and not other.exists()
    assert desktop.entry_path("app").exists() and foreign.exists()


@pytest.mark.skipif(os.environ.get("APPJAIL_INTEGRATION") != "1" or not os.access(desktop.RSVG, os.X_OK),
                    reason="needs bubblewrap and rsvg-convert (APPJAIL_INTEGRATION=1)")
def test_svg_icon_is_rendered_to_png_inside_a_jail(h, xdg):
    def extract(image, dest, fallback=False):
        dest = Path(dest)
        dest.mkdir(parents=True)
        (dest / "AppRun").write_text("#!/bin/sh\n")
        (dest / "app.desktop").write_text("[Desktop Entry]\nName=X\nIcon=logo\n")
        (dest / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg' width='32' height='32'>"
                                       "<rect width='32' height='32' fill='red'/></svg>")
        return 1, 1
    h.add(extract=extract)
    out = run(["desktop", "app", "--yes"]).text
    icon = xdg / "icons/hicolor/256x256/apps/appjail-app.png"
    assert desktop.png_size(icon.read_bytes()) == (256, 256), out
