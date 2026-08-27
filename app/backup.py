import os
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

Runner = Callable[..., object]


def create_database_dump(
    dump_dir: str | Path,
    *,
    now: datetime | None = None,
    runner: Runner = subprocess.run,
) -> Path:
    """Create an atomic custom-format PostgreSQL dump and refresh latest.dump."""
    required = {name: os.getenv(name, "") for name in ("POSTGRES_DB", "POSTGRES_USER")}
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"DB 덤프 환경변수가 없습니다: {', '.join(missing)}")

    destination = Path(dump_dir)
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o700)
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    final_path = destination / f"fruitprice-{timestamp}.dump"
    temporary_path = destination / f".{final_path.name}.tmp"
    latest_temporary = destination / ".latest.dump.tmp"

    command = [
        "pg_dump",
        "--host",
        os.getenv("POSTGRES_HOST", "db"),
        "--port",
        os.getenv("POSTGRES_PORT", "5432"),
        "--username",
        required["POSTGRES_USER"],
        "--dbname",
        required["POSTGRES_DB"],
        "--format",
        "custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(temporary_path),
    ]
    environment = os.environ.copy()
    environment["PGPASSWORD"] = os.getenv("POSTGRES_PASSWORD", "")

    try:
        runner(command, check=True, env=environment, capture_output=True)
        if not temporary_path.exists() or temporary_path.stat().st_size == 0:
            raise RuntimeError("생성된 DB 덤프가 비어 있습니다")
        temporary_path.replace(final_path)
        final_path.chmod(0o600)
        shutil.copyfile(final_path, latest_temporary)
        latest_temporary.chmod(0o600)
        latest_temporary.replace(destination / "latest.dump")
    finally:
        temporary_path.unlink(missing_ok=True)
        latest_temporary.unlink(missing_ok=True)

    return final_path
