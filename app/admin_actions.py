from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, Product, Schedule

MASKED_CREDENTIAL = "••••••••••••"


def mask_credential(encrypted_value: str) -> str:
    """Return a constant mask without decrypting or exposing credential length."""
    return MASKED_CREDENTIAL if encrypted_value else "없음"


async def delete_product_record(session: AsyncSession, product_id: int) -> bool:
    product = await session.get(Product, product_id)
    if not product:
        return False
    await session.delete(product)
    return True


async def delete_schedule_record(
    session: AsyncSession, *, product_id: int, schedule_id: int
) -> bool:
    schedule = await session.get(Schedule, schedule_id)
    if not schedule or schedule.product_id != product_id:
        return False
    await session.execute(
        update(Job).where(Job.schedule_id == schedule_id).values(schedule_id=None)
    )
    await session.delete(schedule)
    return True
