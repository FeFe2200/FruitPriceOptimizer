import asyncio
import secrets
import subprocess
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.middleware.sessions import SessionMiddleware

from app.admin_actions import (
    delete_candidate_record,
    delete_product_record,
    delete_schedule_record,
    mask_credential,
)
from app.backup import create_database_dump
from app.config import settings
from app.db import SessionLocal, create_schema, get_session
from app.models import (
    AuditLog,
    DiscoveryCandidate,
    Job,
    PriceSnapshot,
    Product,
    ProductSource,
    Schedule,
    Site,
    User,
)
from app.scheduling import next_run_after
from app.scraping import (
    validate_login_configuration,
    validate_login_url,
    validate_scrape_url,
)
from app.security import CredentialCipher, hash_password, verify_password
from app.site_presets import SITE_PRESETS

BASE_DIR = Path(__file__).resolve().parent


async def bootstrap_admin() -> None:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.username == settings.admin_username))
        if not user:
            session.add(
                User(
                    username=settings.admin_username,
                    password_hash=hash_password(settings.admin_password),
                    role="admin",
                )
            )
            await session.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await create_schema()
    await bootstrap_admin()
    yield


app = FastAPI(title="FruitPriceOptimizer", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="strict",
    https_only=settings.secure_cookies,
    max_age=8 * 60 * 60,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def check_csrf(request: Request, supplied: str) -> None:
    expected = request.session.get("csrf", "")
    if not expected or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="CSRF 검증에 실패했습니다")


async def current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user = await session.get(User, user_id)
    if not user or not user.active:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다")
    return user


def context(request: Request, user: User | None = None, **values):
    return {"request": request, "user": user, "csrf_token": csrf_token(request), **values}


async def audit(
    session: AsyncSession,
    actor: User,
    action: str,
    entity_type: str,
    entity_id: int | None,
    details: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )


@app.exception_handler(401)
async def unauthorized(_: Request, __):
    return RedirectResponse("/login", status_code=303)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", context(request))


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(),
    password: str = Form(),
    csrf: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    check_csrf(request, csrf)
    user = await session.scalar(select(User).where(User.username == username))
    if not user or not user.active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            context(request, error="아이디 또는 비밀번호가 올바르지 않습니다"),
            status_code=400,
        )
    request.session.clear()
    request.session["user_id"] = user.id
    csrf_token(request)
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
async def logout(request: Request, csrf: str = Form(), _: User = Depends(current_user)):
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    products = (await session.execute(select(Product).order_by(Product.name))).scalars().all()
    jobs = (
        (
            await session.execute(
                select(Job)
                .options(selectinload(Job.product))
                .order_by(Job.queued_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    snapshots = (
        (
            await session.execute(
                select(PriceSnapshot)
                .options(selectinload(PriceSnapshot.product), selectinload(PriceSnapshot.site))
                .order_by(PriceSnapshot.collected_at.desc())
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        context(request, user, products=products, jobs=jobs, snapshots=snapshots),
    )


@app.post("/products")
async def create_product(
    request: Request,
    name: str = Form(),
    keywords: str = Form(default=""),
    csrf: str = Form(),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    check_csrf(request, csrf)
    product = Product(name=name.strip(), keywords=keywords.strip())
    session.add(product)
    await session.flush()
    await audit(session, user, "product.create", "product", product.id)
    await session.commit()
    return RedirectResponse(f"/products/{product.id}", status_code=303)


@app.post("/products/{product_id}/delete")
async def delete_product(
    product_id: int,
    request: Request,
    csrf: str = Form(),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    check_csrf(request, csrf)
    if not await delete_product_record(session, product_id):
        raise HTTPException(404)
    await audit(session, user, "product.delete", "product", product_id)
    await session.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/products/{product_id}", response_class=HTMLResponse)
async def product_detail(
    product_id: int,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    sources = (
        (
            await session.execute(
                select(ProductSource)
                .where(ProductSource.product_id == product_id)
                .options(selectinload(ProductSource.site))
            )
        )
        .scalars()
        .all()
    )
    schedules = (
        (await session.execute(select(Schedule).where(Schedule.product_id == product_id)))
        .scalars()
        .all()
    )
    snapshots = (
        (
            await session.execute(
                select(PriceSnapshot)
                .where(PriceSnapshot.product_id == product_id)
                .options(selectinload(PriceSnapshot.site))
                .order_by(PriceSnapshot.collected_at.desc(), PriceSnapshot.price)
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    candidates = (
        (
            await session.execute(
                select(DiscoveryCandidate)
                .where(DiscoveryCandidate.product_id == product_id)
                .options(selectinload(DiscoveryCandidate.site))
                .order_by(DiscoveryCandidate.discovered_at.desc())
            )
        )
        .scalars()
        .all()
    )
    sites = (await session.execute(select(Site).where(Site.enabled.is_(True)))).scalars().all()
    return templates.TemplateResponse(
        request,
        "product.html",
        context(
            request,
            user,
            product=product,
            sources=sources,
            schedules=schedules,
            snapshots=snapshots,
            candidates=candidates,
            sites=sites,
        ),
    )


@app.post("/products/{product_id}/run")
async def run_comparison(
    product_id: int,
    request: Request,
    csrf: str = Form(),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    check_csrf(request, csrf)
    if not await session.get(Product, product_id):
        raise HTTPException(404)
    job = Job(product_id=product_id, job_type="compare", requested_by=user.id)
    session.add(job)
    await audit(session, user, "comparison.enqueue", "product", product_id)
    await session.commit()
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.post("/products/{product_id}/discover")
async def run_discovery(
    product_id: int,
    request: Request,
    csrf: str = Form(),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    check_csrf(request, csrf)
    if not await session.get(Product, product_id):
        raise HTTPException(404)
    job = Job(product_id=product_id, job_type="discover", requested_by=user.id)
    session.add(job)
    await audit(session, user, "discovery.enqueue", "product", product_id)
    await session.commit()
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.post("/products/{product_id}/candidates/{candidate_id}/delete")
async def delete_candidate(
    product_id: int,
    candidate_id: int,
    request: Request,
    csrf: str = Form(),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    check_csrf(request, csrf)
    if not await delete_candidate_record(session, product_id=product_id, candidate_id=candidate_id):
        raise HTTPException(404)
    await audit(
        session,
        user,
        "candidate.delete",
        "discovery_candidate",
        candidate_id,
        {"product_id": product_id},
    )
    await session.commit()
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.post("/products/{product_id}/sources")
async def create_source(
    product_id: int,
    request: Request,
    site_id: int = Form(),
    page_url: str = Form(),
    row_selector: str = Form(),
    name_selector: str = Form(),
    price_selector: str = Form(),
    pre_click_selector: str = Form(default=""),
    csrf: str = Form(),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    check_csrf(request, csrf)
    if not await session.get(Product, product_id):
        raise HTTPException(404)
    site = await session.get(Site, site_id)
    if not site:
        raise HTTPException(404)
    validate_scrape_url(page_url, site.domain)
    source = ProductSource(
        product_id=product_id,
        site_id=site_id,
        page_url=page_url.strip(),
        row_selector=row_selector.strip(),
        name_selector=name_selector.strip(),
        price_selector=price_selector.strip(),
        pre_click_selector=pre_click_selector.strip(),
    )
    session.add(source)
    await session.flush()
    await audit(session, user, "source.create", "source", source.id, {"site_id": site_id})
    await session.commit()
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.post("/products/{product_id}/schedules")
async def create_schedule(
    product_id: int,
    request: Request,
    cron_expression: str = Form(),
    timezone: str = Form(default="Asia/Seoul"),
    csrf: str = Form(),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    check_csrf(request, csrf)
    if not await session.get(Product, product_id):
        raise HTTPException(404)
    try:
        ZoneInfo(timezone)
        next_run = next_run_after(cron_expression, timezone, datetime.now(UTC))
    except Exception as exc:
        raise HTTPException(400, detail=f"스케줄 형식이 올바르지 않습니다: {exc}") from exc
    schedule = Schedule(
        product_id=product_id,
        cron_expression=cron_expression,
        timezone=timezone,
        next_run_at=next_run,
    )
    session.add(schedule)
    await session.flush()
    await audit(session, user, "schedule.create", "schedule", schedule.id)
    await session.commit()
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.post("/products/{product_id}/schedules/{schedule_id}/delete")
async def delete_schedule(
    product_id: int,
    schedule_id: int,
    request: Request,
    csrf: str = Form(),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    check_csrf(request, csrf)
    if not await delete_schedule_record(session, product_id=product_id, schedule_id=schedule_id):
        raise HTTPException(404)
    await audit(
        session,
        user,
        "schedule.delete",
        "schedule",
        schedule_id,
        {"product_id": product_id},
    )
    await session.commit()
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.get("/sites", response_class=HTMLResponse)
async def sites_page(
    request: Request,
    dumped: str = "",
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    sites = (await session.execute(select(Site).order_by(Site.name))).scalars().all()
    return templates.TemplateResponse(
        request,
        "sites.html",
        context(
            request,
            user,
            sites=sites,
            site_presets=SITE_PRESETS,
            dumped=Path(dumped).name if dumped else "",
        ),
    )


@app.get("/sites/{site_id}", response_class=HTMLResponse)
async def site_detail(
    site_id: int,
    request: Request,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    selected_site = await session.get(Site, site_id)
    if not selected_site:
        raise HTTPException(404)
    sites = (await session.execute(select(Site).order_by(Site.name))).scalars().all()
    return templates.TemplateResponse(
        request,
        "sites.html",
        context(
            request,
            user,
            sites=sites,
            selected_site=selected_site,
            masked_username=mask_credential(selected_site.encrypted_username),
            masked_password=mask_credential(selected_site.encrypted_password),
            site_presets=SITE_PRESETS,
        ),
    )


@app.post("/sites/dump")
async def dump_database(
    request: Request,
    csrf: str = Form(),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    check_csrf(request, csrf)
    try:
        created = await asyncio.to_thread(create_database_dump, settings.db_dump_dir)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        sites = (await session.execute(select(Site).order_by(Site.name))).scalars().all()
        return templates.TemplateResponse(
            request,
            "sites.html",
            context(
                request,
                user,
                sites=sites,
                site_presets=SITE_PRESETS,
                error=f"DB 덤프에 실패했습니다: {exc}",
            ),
            status_code=500,
        )
    await audit(session, user, "database.dump", "database", None, {"file": created.name})
    await session.commit()
    return RedirectResponse(f"/sites?dumped={created.name}", status_code=303)


@app.post("/sites")
async def create_site(
    request: Request,
    name: str = Form(),
    domain: str = Form(),
    catalog_url: str = Form(),
    login_url: str = Form(default=""),
    login_pre_click_selector: str = Form(default=""),
    username_selector: str = Form(default=""),
    password_selector: str = Form(default=""),
    submit_selector: str = Form(default=""),
    site_username: str = Form(default=""),
    site_password: str = Form(default=""),
    csrf: str = Form(),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    check_csrf(request, csrf)
    form_values = {
        "name": name,
        "domain": domain,
        "catalog_url": catalog_url,
        "login_url": login_url,
        "login_pre_click_selector": login_pre_click_selector,
        "username_selector": username_selector,
        "password_selector": password_selector,
        "submit_selector": submit_selector,
    }
    try:
        normalized_domain = domain.strip().lower()
        if "://" in normalized_domain:
            normalized_domain = urlparse(normalized_domain).hostname or ""
        validate_scrape_url(catalog_url, normalized_domain)
        validate_login_configuration(
            login_url,
            site_username,
            site_password,
            username_selector,
            password_selector,
            submit_selector,
        )
        if login_url:
            validate_login_url(login_url, normalized_domain, bool(site_username or site_password))
    except ValueError as exc:
        sites = (await session.execute(select(Site).order_by(Site.name))).scalars().all()
        return templates.TemplateResponse(
            request,
            "sites.html",
            context(
                request,
                user,
                sites=sites,
                site_presets=SITE_PRESETS,
                error=str(exc),
                form=form_values,
            ),
            status_code=400,
        )
    cipher = CredentialCipher(settings.credential_key)
    site = Site(
        name=name.strip(),
        domain=normalized_domain,
        catalog_url=catalog_url.strip(),
        login_url=login_url.strip(),
        login_pre_click_selector=login_pre_click_selector.strip(),
        username_selector=username_selector.strip(),
        password_selector=password_selector.strip(),
        submit_selector=submit_selector.strip(),
        encrypted_username=cipher.encrypt(site_username),
        encrypted_password=cipher.encrypt(site_password),
    )
    session.add(site)
    await session.flush()
    await audit(
        session,
        user,
        "site.create",
        "site",
        site.id,
        {"domain": normalized_domain, "credentials_stored": bool(site_username)},
    )
    await session.commit()
    return RedirectResponse("/sites", status_code=303)


@app.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    users = (await session.execute(select(User).order_by(User.username))).scalars().all()
    return templates.TemplateResponse(request, "users.html", context(request, user, users=users))


@app.post("/users")
async def create_user(
    request: Request,
    username: str = Form(),
    password: str = Form(),
    role: str = Form(default="viewer"),
    csrf: str = Form(),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    check_csrf(request, csrf)
    if role not in {"admin", "viewer"}:
        raise HTTPException(400, detail="유효하지 않은 역할입니다")
    if len(password) < 12:
        raise HTTPException(400, detail="비밀번호는 12자 이상이어야 합니다")
    new_user = User(username=username.strip(), password_hash=hash_password(password), role=role)
    session.add(new_user)
    await session.flush()
    await audit(session, user, "user.create", "user", new_user.id, {"role": role})
    await session.commit()
    return RedirectResponse("/users", status_code=303)
