"""Enforce dependency direction and diagnostic privacy at repository boundaries."""

import ast
from pathlib import Path

import pytest

from scripts import check_privacy
from scripts.check_privacy import findings

ROOT = Path(__file__).resolve().parents[1]


def test_cleaning_domain_and_use_case_only_depend_on_standard_library_and_domain():
    pure = {"actions", "application", "capabilities", "cleaning", "dock", "preferences"}
    standard = {"asyncio", "dataclasses", "datetime", "enum", "typing"}
    domain = pure | {"errors"}
    for module in pure:
        path = ROOT / f"custom_components/roomba_home/core/{module}.py"
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert all(name.name.split(".")[0] in standard for name in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module.split(".")[0] in (domain if node.level else standard)


def test_core_does_not_import_home_assistant_or_cli_composition():
    for file in (ROOT / "custom_components/roomba_home/core").glob("*.py"):
        for node in ast.walk(ast.parse(file.read_text())):
            if isinstance(node, ast.Import):
                modules = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            assert all(
                m.split(".")[0] not in {"homeassistant", "tools", "scripts"} for m in modules
            )


def test_privacy_scanner_reports_classification_and_location_without_matching_value():
    private = "fixture-private-value"
    assert list(findings("safe\n" + private, [private])) == [("private-input-value", 2)]
    address = "person" + "@" + "private-domain" + ".test"
    assert list(findings(address)) == [("personal-email", 1)]
    assert not list(findings("person@example.test"))
    assert not list(findings("brand/icon@2x.png"))
    assert list(findings("person" + "@" + "2x.png")) == [("personal-email", 1)]


def test_privacy_scanner_detects_cloud_credentials_and_private_keys():
    assert list(findings("AS" + "IA" + "X" * 16)) == [("aws-access-key", 1)]
    assert list(findings("-----BEGIN " + "PRIVATE KEY-----")) == [("private-key", 1)]


@pytest.mark.parametrize("case,expected", [("approved", 0), ("modified", 1), ("unknown", 1)])
def test_only_exact_reviewed_artwork_is_accepted_as_binary(
    tmp_path, monkeypatch, capsys, case, expected
):
    relative = "custom_components/roomba_home/brand/icon.png"
    data = (ROOT / relative).read_bytes()
    if case == "modified":
        data += b"fixture-private-value"
    elif case == "unknown":
        relative = "unreviewed.png"
    file = tmp_path / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)
    monkeypatch.setattr(check_privacy, "ROOT", tmp_path)
    monkeypatch.setattr(
        check_privacy.subprocess, "check_output", lambda *a, **k: (relative + "\0").encode()
    )
    monkeypatch.setattr("sys.argv", ["check_privacy.py"])
    assert check_privacy.main() == expected
    assert "fixture-private-value" not in capsys.readouterr().out
