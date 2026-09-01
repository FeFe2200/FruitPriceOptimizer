import asyncio
import os

from playwright.async_api import async_playwright
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import AuditLog, DiscoveryCandidate, Product, Site

BASE_URL = os.getenv("SMOKE_BASE_URL", "http://web:8000")
PRODUCT_NAME = "후보 UI 격리 테스트 상품"
DISABLED_SITE_NAME = "후보 UI 격리 테스트 비활성 사이트"
HOSTILE_TITLE = '후보 "테스트" <img src=x onerror=alert(1)>'


async def seed_records() -> tuple[int, int, int, str, int]:
    async with SessionLocal() as session:
        await session.execute(delete(Product).where(Product.name == PRODUCT_NAME))
        await session.execute(delete(Site).where(Site.name == DISABLED_SITE_NAME))
        enabled_site = await session.scalar(
            select(Site).where(Site.enabled.is_(True)).order_by(Site.id)
        )
        if not enabled_site:
            raise RuntimeError("candidate UI test requires an enabled site")

        product = Product(name=PRODUCT_NAME, keywords="candidate ui smoke")
        disabled_site = Site(
            name=DISABLED_SITE_NAME,
            domain="example.com",
            catalog_url="https://example.com/products",
            enabled=False,
        )
        session.add_all([product, disabled_site])
        await session.flush()
        candidate_url = enabled_site.catalog_url + "#candidate-ui-test"
        enabled_candidate = DiscoveryCandidate(
            product_id=product.id,
            site_id=enabled_site.id,
            title=HOSTILE_TITLE,
            page_url=candidate_url,
        )
        disabled_candidate = DiscoveryCandidate(
            product_id=product.id,
            site_id=disabled_site.id,
            title="비활성 사이트 후보",
            page_url="https://example.com/products/disabled-candidate",
        )
        session.add_all([enabled_candidate, disabled_candidate])
        await session.commit()
        return (
            product.id,
            enabled_candidate.id,
            enabled_site.id,
            candidate_url,
            disabled_candidate.id,
        )


async def cleanup_records() -> None:
    async with SessionLocal() as session:
        await session.execute(delete(Product).where(Product.name == PRODUCT_NAME))
        await session.execute(delete(Site).where(Site.name == DISABLED_SITE_NAME))
        await session.commit()


async def verify_database(candidate_id: int) -> None:
    async with SessionLocal() as session:
        if await session.get(DiscoveryCandidate, candidate_id):
            raise RuntimeError("candidate still exists after UI deletion")
        audit_log = await session.scalar(
            select(AuditLog)
            .where(
                AuditLog.action == "candidate.delete",
                AuditLog.entity_id == candidate_id,
            )
            .order_by(AuditLog.id.desc())
        )
        if not audit_log:
            raise RuntimeError("candidate deletion audit log was not committed")


async def main() -> None:
    product_id, candidate_id, site_id, candidate_url, disabled_candidate_id = await seed_records()
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(BASE_URL + "/login")
            await page.locator('input[name="username"]').fill(os.getenv("ADMIN_USERNAME", "admin"))
            await page.locator('input[name="password"]').fill(os.environ["ADMIN_PASSWORD"])
            await page.get_by_role("button", name="로그인").click()
            await page.wait_for_url(BASE_URL + "/")
            await page.goto(f"{BASE_URL}/products/{product_id}")

            if await page.locator("img[onerror]").count():
                raise RuntimeError("candidate title was interpreted as executable markup")
            select_button = page.locator(
                f'button.candidate-select[data-candidate-id="{candidate_id}"]'
            ).last
            await select_button.click()
            if await page.locator('#source-form select[name="site_id"]').input_value() != str(
                site_id
            ):
                raise RuntimeError("candidate site was not populated")
            if (
                await page.locator('#source-form input[name="page_url"]').input_value()
                != candidate_url
            ):
                raise RuntimeError("candidate URL was not populated")
            if HOSTILE_TITLE not in await page.locator("#candidate-selection-message").inner_text():
                raise RuntimeError("candidate selection feedback is incorrect")

            disabled_button = page.locator(
                f'button.candidate-select[data-candidate-id="{disabled_candidate_id}"]'
            )
            if not await disabled_button.is_disabled():
                raise RuntimeError("disabled-site candidate can still populate the form")

            page.once("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
            delete_form = page.locator(
                f'form[action="/products/{product_id}/candidates/{candidate_id}/delete"]'
            )
            await delete_form.get_by_role("button", name="삭제").click()
            await page.wait_for_url(f"{BASE_URL}/products/{product_id}")
            await browser.close()

        await verify_database(candidate_id)
        print(
            "candidate UI integration test passed: safe rendering, form fill, disabled site, delete"
        )
    finally:
        await cleanup_records()


if __name__ == "__main__":
    asyncio.run(main())
