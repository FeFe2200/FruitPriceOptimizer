import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.db import SessionLocal, create_schema
from app.models import Job, Schedule
from app.scheduling import next_run_after


async def enqueue_due_schedules() -> int:
    now = datetime.now(UTC)
    count = 0
    async with SessionLocal() as session:
        async with session.begin():
            schedules = (
                await session.execute(
                    select(Schedule)
                    .where(Schedule.enabled.is_(True), Schedule.next_run_at <= now)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
            for schedule in schedules:
                session.add(
                    Job(
                        job_type="compare",
                        product_id=schedule.product_id,
                        schedule_id=schedule.id,
                    )
                )
                schedule.next_run_at = next_run_after(
                    schedule.cron_expression, schedule.timezone, now
                )
                count += 1
    return count


async def scheduler_loop() -> None:
    await create_schema()
    while True:
        await enqueue_due_schedules()
        await asyncio.sleep(20)


if __name__ == "__main__":
    asyncio.run(scheduler_loop())
