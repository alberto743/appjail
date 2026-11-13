# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The tables of docs/compositor-assessment/ASSESSMENT.md are the ones tests/compositors/report.py makes from the saved results."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs" / "compositor-assessment" / "ASSESSMENT.md"

pytestmark = pytest.mark.skipif(not DOCUMENT.is_file(), reason="the measurements are not in this tree")


def report():
    spec = importlib.util.spec_from_file_location("report", ROOT / "tests" / "compositors" / "report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_generated_tables_are_what_the_saved_results_give():
    text = DOCUMENT.read_text()
    assert report().splice(text, report().sections()) == text, "run: python3 tests/compositors/report.py --write"


def test_every_table_the_document_names_can_be_generated_and_none_is_missing():
    module = report()
    named = {m.group(2) for m in module.BLOCK.finditer(DOCUMENT.read_text())}
    assert named == {"wayland", "rule", "clipboard", "dbus", "mutter_dbus"}
    assert named <= set(module.sections())


def test_an_unknown_block_is_an_error():
    with pytest.raises(ValueError, match="unknown"):
        report().splice("<!-- generated:nope -->\nx\n<!-- /generated -->", {})
