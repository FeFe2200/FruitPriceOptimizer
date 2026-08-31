from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.admin_actions import delete_product_record, delete_schedule_record, mask_credential


def test_mask_credential_never_exposes_ciphertext_or_plaintext_shape():
    ciphertext = "gAAAAABciphertext-that-must-not-be-rendered"

    masked = mask_credential(ciphertext)

    assert masked == "••••••••••••"
    assert ciphertext not in masked
    assert mask_credential("") == "없음"


@pytest.mark.asyncio
async def test_delete_product_record_deletes_existing_product():
    product = SimpleNamespace(id=7)
    session = SimpleNamespace(get=AsyncMock(return_value=product), delete=AsyncMock())

    deleted = await delete_product_record(session, 7)

    assert deleted is True
    session.get.assert_awaited_once()
    session.delete.assert_awaited_once_with(product)


@pytest.mark.asyncio
async def test_delete_schedule_record_requires_matching_product_and_detaches_jobs():
    schedule = SimpleNamespace(id=11, product_id=2)
    session = SimpleNamespace(
        get=AsyncMock(return_value=schedule),
        execute=AsyncMock(),
        delete=AsyncMock(),
    )

    assert await delete_schedule_record(session, product_id=2, schedule_id=11) is True
    session.execute.assert_awaited_once()
    session.delete.assert_awaited_once_with(schedule)

    session.execute.reset_mock()
    session.delete.reset_mock()
    assert await delete_schedule_record(session, product_id=99, schedule_id=11) is False
    session.execute.assert_not_awaited()
    session.delete.assert_not_awaited()
