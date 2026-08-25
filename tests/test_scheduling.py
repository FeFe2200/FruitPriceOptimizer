from datetime import UTC, datetime

from app.scheduling import next_run_after


def test_daily_schedule_uses_requested_timezone():
    now = datetime(2026, 8, 19, 0, 30, tzinfo=UTC)  # 09:30 Asia/Seoul

    result = next_run_after("0 10 * * *", "Asia/Seoul", now)

    assert result == datetime(2026, 8, 19, 1, 0, tzinfo=UTC)


def test_next_run_moves_to_tomorrow_after_time_passed():
    now = datetime(2026, 8, 19, 2, 0, tzinfo=UTC)  # 11:00 Asia/Seoul

    result = next_run_after("0 10 * * *", "Asia/Seoul", now)

    assert result == datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
