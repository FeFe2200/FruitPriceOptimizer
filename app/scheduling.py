from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from croniter import croniter


def next_run_after(cron_expression: str, timezone: str, now: datetime | None = None) -> datetime:
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        raise ValueError("now는 timezone-aware datetime이어야 합니다")
    local_reference = reference.astimezone(ZoneInfo(timezone))
    next_local = croniter(cron_expression, local_reference).get_next(datetime)
    return next_local.astimezone(UTC)
