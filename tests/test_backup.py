from datetime import UTC, datetime
from pathlib import Path
from stat import S_IMODE

from app.backup import create_database_dump


def test_database_dump_is_versioned_and_updates_latest(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_DB", "fruit_prices")
    monkeypatch.setenv("POSTGRES_USER", "fruit_app")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    calls = []

    def fake_run(command, *, check, env, capture_output):
        calls.append((command, check, env, capture_output))
        output = Path(command[command.index("--file") + 1])
        output.write_bytes(b"PGDMP test backup")

    created = create_database_dump(
        tmp_path,
        now=datetime(2026, 8, 27, 14, 30, 15, tzinfo=UTC),
        runner=fake_run,
    )

    assert created.name == "fruitprice-20260827-143015.dump"
    assert created.read_bytes() == b"PGDMP test backup"
    assert (tmp_path / "latest.dump").read_bytes() == created.read_bytes()
    assert S_IMODE(created.stat().st_mode) == 0o600
    assert S_IMODE((tmp_path / "latest.dump").stat().st_mode) == 0o600
    assert S_IMODE(tmp_path.stat().st_mode) == 0o700
    command, check, env, capture_output = calls[0]
    assert command[:2] == ["pg_dump", "--host"]
    assert "secret" not in command
    assert env["PGPASSWORD"] == "secret"
    assert check is True
    assert capture_output is True


def test_failed_or_empty_dump_does_not_replace_latest(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_DB", "fruit_prices")
    monkeypatch.setenv("POSTGRES_USER", "fruit_app")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    latest = tmp_path / "latest.dump"
    latest.write_bytes(b"known-good")

    def fake_run(command, *, check, env, capture_output):
        Path(command[command.index("--file") + 1]).write_bytes(b"")

    try:
        create_database_dump(tmp_path, runner=fake_run)
    except RuntimeError as exc:
        assert "비어" in str(exc)
    else:
        raise AssertionError("empty dump must fail")

    assert latest.read_bytes() == b"known-good"
