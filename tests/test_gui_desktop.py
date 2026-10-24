# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The menu entry and icon of appjail-gui itself (`appjail-gui --desktop` / `--remove-desktop`). No display needed."""

import shutil
import subprocess
from importlib import resources

import pytest

from appjail import desktop
from appjail import gui as gui_package
from appjail.gui import main

ARGV = ["/opt/appjail/bin/appjail-gui"]


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(desktop, "gui_launcher_argv", lambda: ARGV)
    return tmp_path / "xdg"


def test_flag_creates_entry_and_icon(xdg, capsys):
    assert main(["--desktop"]) == 0
    text = (xdg / "applications/appjail.desktop").read_text()
    assert "Exec=/opt/appjail/bin/appjail-gui\n" in text and "Icon=appjail\n" in text
    assert "X-Appjail-GUI=true" in text and "Terminal=false" in text and "Name=appjail\n" in text
    icon = xdg / "icons/hicolor/scalable/apps/appjail.svg"
    assert icon.read_bytes() == resources.files(gui_package).joinpath("appjail.svg").read_bytes()
    assert b"<svg" in icon.read_bytes()
    assert "appjail.desktop" in capsys.readouterr().out


def test_flag_is_idempotent_and_refreshes(xdg):
    assert main(["--desktop"]) == 0
    (xdg / "applications/appjail.desktop").write_text("[Desktop Entry]\nX-Appjail-GUI=true\nExec=old\n")
    assert main(["--desktop"]) == 0
    assert "Exec=/opt/appjail/bin/appjail-gui" in (xdg / "applications/appjail.desktop").read_text()


def test_exec_with_spaces_is_quoted(xdg, monkeypatch):
    monkeypatch.setattr(desktop, "gui_launcher_argv", lambda: ["/opt/my apps/python3", "-m", "appjail.gui"])
    main(["--desktop"])
    assert 'Exec="/opt/my apps/python3" -m appjail.gui\n' in (xdg / "applications/appjail.desktop").read_text()


def test_foreign_file_is_never_replaced_or_removed(xdg, capsys):
    path = xdg / "applications/appjail.desktop"
    path.parent.mkdir(parents=True)
    path.write_text("[Desktop Entry]\nName=mine\n")
    assert main(["--desktop"]) == 1
    assert "not created by appjail-gui" in capsys.readouterr().err
    assert main(["--remove-desktop"]) == 0
    assert path.read_text() == "[Desktop Entry]\nName=mine\n"
    assert not (xdg / "icons/hicolor/scalable/apps/appjail.svg").exists()


def test_remove_deletes_entry_and_icon(xdg, capsys):
    main(["--desktop"])
    capsys.readouterr()
    assert main(["--remove-desktop"]) == 0
    assert not (xdg / "applications/appjail.desktop").exists()
    assert not (xdg / "icons/hicolor/scalable/apps/appjail.svg").exists()
    assert "Removed" in capsys.readouterr().out
    assert main(["--remove-desktop"]) == 0
    assert "No menu entry" in capsys.readouterr().out


def test_both_flags_together_are_refused(xdg):
    with pytest.raises(SystemExit):
        main(["--desktop", "--remove-desktop"])


def test_app_entries_and_pruning_ignore_it(xdg):
    main(["--desktop"])
    assert desktop.dangling() == []
    assert desktop.marker_of(desktop.gui_entry_path()) is None


def test_symlinked_entry_is_not_followed(xdg, tmp_path):
    target = tmp_path / "elsewhere.desktop"
    target.write_text("[Desktop Entry]\nX-Appjail-GUI=true\n")
    (xdg / "applications").mkdir(parents=True)
    (xdg / "applications/appjail.desktop").symlink_to(target)
    assert main(["--remove-desktop"]) == 0
    assert target.exists() and (xdg / "applications/appjail.desktop").is_symlink()
    assert main(["--desktop"]) == 1
    assert target.read_text() == "[Desktop Entry]\nX-Appjail-GUI=true\n"


@pytest.mark.skipif(not shutil.which("desktop-file-validate"), reason="desktop-file-utils not installed")
def test_entry_validates(xdg):
    main(["--desktop"])
    proc = subprocess.run(["desktop-file-validate", str(xdg / "applications/appjail.desktop")], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
