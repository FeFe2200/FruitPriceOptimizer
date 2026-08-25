import ipaddress
import re
from decimal import Decimal
from urllib.parse import urlparse

from bs4 import BeautifulSoup


def credential_request_allowed(url: str, registered_domain: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    domain = registered_domain.lower().rstrip(".")
    return parsed.scheme in {"https", "wss"} and hostname == domain


def validate_login_configuration(
    login_url: str,
    username: str,
    password: str,
    username_selector: str,
    password_selector: str,
    submit_selector: str,
) -> None:
    fields = [username, password, username_selector, password_selector, submit_selector]
    if any(fields) and not login_url:
        raise ValueError("자격증명을 저장하려면 로그인 URL이 필요합니다")
    if login_url and not all(fields):
        raise ValueError("로그인 URL, 자격증명, 선택자를 모두 입력해야 합니다")


def validate_login_url(url: str, registered_domain: str, credentials_present: bool) -> str:
    validated = validate_scrape_url(url, registered_domain)
    if credentials_present and urlparse(validated).scheme != "https":
        raise ValueError("사이트 자격증명은 HTTPS 로그인 URL에서만 사용할 수 있습니다")
    return validated


def validate_scrape_url(url: str, registered_domain: str | None) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("http 또는 https 상품 URL이 필요합니다")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost":
        raise ValueError("내부 네트워크 주소에는 접근할 수 없습니다")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise ValueError("내부 네트워크 주소에는 접근할 수 없습니다")
    if registered_domain:
        domain = registered_domain.lower().rstrip(".")
        if hostname != domain:
            raise ValueError("URL이 등록된 도메인과 일치하지 않습니다")
    return url


def _parse_amount(text: str) -> Decimal:
    digits = re.sub(r"[^0-9.]", "", text)
    if not digits:
        raise ValueError(f"가격을 숫자로 변환할 수 없습니다: {text}")
    return Decimal(digits)


def extract_prices(
    html: str,
    row_selector: str,
    name_selector: str,
    price_selector: str,
) -> list[tuple[str, Decimal]]:
    soup = BeautifulSoup(html, "html.parser")
    result: list[tuple[str, Decimal]] = []
    for row in soup.select(row_selector):
        name_node = row.select_one(name_selector)
        price_node = row.select_one(price_selector)
        if not name_node or not price_node:
            continue
        result.append((name_node.get_text(" ", strip=True), _parse_amount(price_node.get_text())))
    if not result:
        raise ValueError("가격 행을 찾지 못했습니다")
    return result
