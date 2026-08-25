import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.crawler import discover_product, scrape_source, sleep_between_runs
from app.db import SessionLocal, create_schema
from app.models import DiscoveryCandidate, Job, PriceSnapshot, Product, ProductSource, Site
from app.security import CredentialCipher


async def claim_job() -> int | None:
    async with SessionLocal() as session:
        async with session.begin():
            statement = (
                select(Job)
                .where(Job.status == "queued")
                .order_by(Job.queued_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            job = (await session.execute(statement)).scalar_one_or_none()
            if not job:
                return None
            job.status = "running"
            job.started_at = datetime.now(UTC)
            return job.id


async def process_compare(job: Job, cipher: CredentialCipher) -> None:
    async with SessionLocal() as session:
        product = (
            await session.execute(
                select(Product)
                .where(Product.id == job.product_id)
                .options(selectinload(Product.sources).selectinload(ProductSource.site))
            )
        ).scalar_one()
        if not product.sources:
            raise ValueError("승인된 상품 페이지가 없습니다")
        product_id = product.id
        sources = list(product.sources)
    collected = []
    for source in sources:
        if not source.enabled or not source.site.enabled:
            continue
        rows = await scrape_source(source, source.site, cipher)
        collected.extend((source, option_name, price) for option_name, price in rows)
    async with SessionLocal() as session:
        for source, option_name, price in collected:
            session.add(
                PriceSnapshot(
                    job_id=job.id,
                    product_id=product_id,
                    source_id=source.id,
                    site_id=source.site_id,
                    option_name=option_name,
                    price=price,
                )
            )
        await session.commit()


async def process_discovery(job: Job, cipher: CredentialCipher) -> None:
    async with SessionLocal() as session:
        product = await session.get(Product, job.product_id)
        sites = list((await session.execute(select(Site).where(Site.enabled.is_(True)))).scalars())
    for site in sites:
        candidates = await discover_product(site, product, cipher)
        async with SessionLocal() as session:
            for candidate in candidates:
                exists = await session.scalar(
                    select(DiscoveryCandidate.id).where(
                        DiscoveryCandidate.product_id == product.id,
                        DiscoveryCandidate.site_id == site.id,
                        DiscoveryCandidate.page_url == candidate.url,
                    )
                )
                if not exists:
                    session.add(
                        DiscoveryCandidate(
                            product_id=product.id,
                            site_id=site.id,
                            title=candidate.title,
                            page_url=candidate.url,
                        )
                    )
            await session.commit()


async def process_job(job_id: int) -> None:
    cipher = CredentialCipher(settings.credential_key)
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
    try:
        if job.job_type == "discover":
            await process_discovery(job, cipher)
        else:
            await process_compare(job, cipher)
        status, error = "completed", ""
    except Exception as exc:  # worker boundary records failure for the UI
        status, error = "failed", str(exc)[:4000]
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        job.status = status
        job.error = error
        job.finished_at = datetime.now(UTC)
        await session.commit()


async def worker_loop() -> None:
    await create_schema()
    while True:
        job_id = await claim_job()
        if job_id:
            await process_job(job_id)
        else:
            await sleep_between_runs()


if __name__ == "__main__":
    asyncio.run(worker_loop())
