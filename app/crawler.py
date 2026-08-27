import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from playwright.async_api import Browser, Page, Route, WebSocketRoute, async_playwright

from app.config import settings
from app.models import Product, ProductSource, Site
from app.scraping import (
    credential_request_allowed,
    extract_prices,
    validate_login_url,
    validate_scrape_url,
)
from app.security import CredentialCipher

NETWORK_LOCKDOWN_SCRIPT = """
for (const name of ['RTCPeerConnection', 'webkitRTCPeerConnection', 'WebTransport']) {
  Object.defineProperty(globalThis, name, {
    value: undefined,
    writable: false,
    configurable: false
  });
}
"""


@dataclass
class FoundPage:
    title: str
    url: str


async def _resolve_public_ipv4(domain: str) -> str:
    addresses = await asyncio.get_running_loop().getaddrinfo(
        domain, None, family=socket.AF_INET, type=socket.SOCK_STREAM
    )
    public = sorted(
        {str(item[4][0]) for item in addresses if ipaddress.ip_address(item[4][0]).is_global}
    )
    if not public:
        raise ValueError("등록 도메인이 공인 IPv4 주소로 확인되지 않습니다")
    return public[0]


async def _launch_browser(playwright, domain: str) -> Browser:
    pinned_ip = await _resolve_public_ipv4(domain)
    rules = f"MAP {domain} {pinned_ip},EXCLUDE localhost"
    return await playwright.chromium.launch(
        headless=True,
        args=[
            f"--host-resolver-rules={rules}",
            "--disable-quic",
            "--dns-prefetch-disable",
            "--disable-background-networking",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--disable-features=WebTransport,WebTransportDeveloperMode",
        ],
    )


async def _guard_request(route: Route) -> None:
    parsed = urlparse(route.request.url)
    host = parsed.hostname or ""
    blocked = host == "localhost"
    try:
        blocked = blocked or not ipaddress.ip_address(host).is_global
    except ValueError:
        try:
            addresses = await asyncio.get_running_loop().getaddrinfo(
                host, None, type=socket.SOCK_STREAM
            )
            blocked = blocked or any(
                not ipaddress.ip_address(item[4][0]).is_global for item in addresses
            )
        except socket.gaierror:
            blocked = True
    if parsed.scheme not in {"http", "https", "data", "blob"} or blocked:
        await route.abort()
    else:
        await route.continue_()


async def _login(page: Page, site: Site, cipher: CredentialCipher) -> None:
    if not site.login_url or not site.encrypted_username:
        return
    required = [site.username_selector, site.password_selector, site.submit_selector]
    if not all(required):
        raise ValueError("로그인 선택자 3개를 모두 등록해야 합니다")
    validate_login_url(site.login_url, site.domain, True)
    await page.goto(site.login_url, wait_until="domcontentloaded")
    validate_login_url(page.url, site.domain, True)
    if site.login_pre_click_selector:
        await page.locator(site.login_pre_click_selector).click()
    submit = page.locator(site.submit_selector)
    form_action = await submit.evaluate(
        "element => element.formAction || (element.form ? element.form.action : '')"
    )
    if not form_action:
        raise ValueError("로그인 버튼이 유효한 form에 연결되어 있지 않습니다")
    validate_login_url(form_action, site.domain, True)

    await page.locator(site.username_selector).fill(cipher.decrypt(site.encrypted_username))
    await page.locator(site.password_selector).fill(cipher.decrypt(site.encrypted_password))
    await submit.click()
    await page.wait_for_load_state("networkidle")
    validate_login_url(page.url, site.domain, True)


async def _new_page(browser: Browser, restricted_domain: str | None = None) -> Page:
    context = await browser.new_context(locale="ko-KR", service_workers="block")
    await context.add_init_script(NETWORK_LOCKDOWN_SCRIPT)

    async def credential_guard(route: Route) -> None:
        if restricted_domain and credential_request_allowed(route.request.url, restricted_domain):
            await _guard_request(route)
        else:
            await route.abort()

    async def websocket_guard(websocket: WebSocketRoute) -> None:
        if restricted_domain and credential_request_allowed(websocket.url, restricted_domain):
            await websocket.connect_to_server()
        else:
            await websocket.close(code=1008, reason="Cross-domain credential channel blocked")

    if restricted_domain:
        await context.route("**/*", credential_guard)
        await context.route_web_socket("**/*", websocket_guard)
    else:
        await context.route("**/*", _guard_request)
    page = await context.new_page()
    page.set_default_timeout(settings.scrape_timeout_ms)
    return page


async def scrape_source(source: ProductSource, site: Site, cipher: CredentialCipher):
    validate_scrape_url(source.page_url, site.domain)
    async with async_playwright() as playwright:
        browser = await _launch_browser(playwright, site.domain)
        try:
            page = await _new_page(browser, site.domain)
            await _login(page, site, cipher)
            await page.goto(source.page_url, wait_until="networkidle")
            if source.pre_click_selector:
                await page.locator(source.pre_click_selector).click()
                await page.wait_for_timeout(1000)
            return extract_prices(
                await page.content(),
                source.row_selector,
                source.name_selector,
                source.price_selector,
            )
        finally:
            await browser.close()


async def discover_product(
    site: Site, product: Product, cipher: CredentialCipher
) -> list[FoundPage]:
    validate_scrape_url(site.catalog_url, site.domain)
    keywords = [part.strip().lower() for part in product.keywords.split(",") if part.strip()]
    keywords.append(product.name.lower())
    async with async_playwright() as playwright:
        browser = await _launch_browser(playwright, site.domain)
        try:
            page = await _new_page(browser, site.domain)
            await _login(page, site, cipher)
            await page.goto(site.catalog_url, wait_until="networkidle")
            anchors = await page.locator("a[href]").all()
            found: dict[str, FoundPage] = {}
            for anchor in anchors:
                title = (await anchor.inner_text()).strip()
                if not title or not any(word in title.lower() for word in keywords):
                    continue
                href = await anchor.get_attribute("href")
                if not href:
                    continue
                url = urljoin(site.catalog_url, href)
                try:
                    validate_scrape_url(url, site.domain)
                except ValueError:
                    continue
                found[url] = FoundPage(title=title, url=url)
            return list(found.values())
        finally:
            await browser.close()


async def sleep_between_runs(seconds: int = 3) -> None:
    await asyncio.sleep(seconds)
