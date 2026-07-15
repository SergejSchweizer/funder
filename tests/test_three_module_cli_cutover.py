from __future__ import annotations

import json

from founder.refresh.cli import main as refresh_main
from founder.selection.cli import main as selection_main
from founder.update.cli import main as update_main


def test_refresh_standalone_cli_builds_deterministic_plan(capsys) -> None:  # type: ignore[no-untyped-def]
    refresh_main(
        [
            "plan",
            "--run-id",
            "refresh-1",
            "--exchange",
            "XETRA",
            "--exchange",
            "AS",
            "--dry-run",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "concurrency": 2,
        "dry_run": True,
        "exchanges": ["XETRA", "AS"],
        "resume": "",
        "run_id": "refresh-1",
    }

    refresh_main(["version"])
    assert json.loads(capsys.readouterr().out)["contract_version"] == "refresh@v1"

    refresh_main(["status"])
    assert json.loads(capsys.readouterr().out) == {"state": "none"}


def test_selection_standalone_cli_exposes_fields_and_create_shell(capsys) -> None:  # type: ignore[no-untyped-def]
    selection_main(["fields"])
    fields_payload = json.loads(capsys.readouterr().out)
    assert any(field["name"] == "exchange" for field in fields_payload["fields"])

    selection_main(
        [
            "create",
            "--refresh-snapshot",
            "catalog_1",
            "--filter",
            "exchange",
            "eq",
            "XETRA",
            "--filter",
            "annualized_volatility",
            "lte",
            "0.2",
        ]
    )
    create_payload = json.loads(capsys.readouterr().out)
    assert create_payload["name"].startswith("exchange_eq_xetra_annualized_volatility_lte_0.2")
    assert create_payload["metric_requirements"] == ["annualized_volatility"]

    selection_main(["version"])
    assert json.loads(capsys.readouterr().out)["contract_version"] == "selection@v1"

    selection_main(["status"])
    assert json.loads(capsys.readouterr().out) == {"state": "none"}


def test_update_standalone_cli_builds_selection_scoped_request(capsys) -> None:  # type: ignore[no-untyped-def]
    update_main(
        [
            "plan",
            "--selection",
            "selection_1",
            "--run-id",
            "update-1",
            "--concurrency",
            "2",
            "--dry-run",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "concurrency": 2,
        "dry_run": True,
        "run_id": "update-1",
        "selection_id": "selection_1",
    }

    update_main(["version"])
    assert json.loads(capsys.readouterr().out)["contract_version"] == "update@v1"

    update_main(["status"])
    assert json.loads(capsys.readouterr().out) == {"state": "none"}
