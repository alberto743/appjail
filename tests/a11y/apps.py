# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Test windows for the accessibility measurements: one GTK 3 and one Qt 6 push button (guest only).

Usage: apps.py gtk|qt SECONDS
"""

import os
import sys


def gtk(seconds):
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    window = Gtk.Window(title="appjail-a11y-gtk")
    window.add(Gtk.Button(label="Press me"))
    window.show_all()
    GLib.timeout_add_seconds(seconds, Gtk.main_quit)
    Gtk.main()


def qt(seconds):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QPushButton

    app = QApplication(sys.argv)
    button = QPushButton("Press me qt")
    button.setWindowTitle("appjail-a11y-qt")
    button.show()
    QTimer.singleShot(seconds * 1000, app.quit)
    app.exec()


if __name__ == "__main__":
    print("AT_SPI_BUS_ADDRESS =", os.environ.get("AT_SPI_BUS_ADDRESS"), "session bus =",
          os.environ.get("DBUS_SESSION_BUS_ADDRESS"), flush=True)
    (gtk if sys.argv[1] == "gtk" else qt)(int(sys.argv[2]))
