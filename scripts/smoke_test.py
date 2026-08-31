import http.cookiejar
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup, Tag

BASE_URL = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    if not match:
        raise RuntimeError("CSRF token not found")
    return match.group(1)


def post(opener, path: str, data: dict[str, str]) -> str:
    request = urllib.request.Request(  # noqa: S310 - fixed local smoke-test URL
        BASE_URL + path,
        data=urllib.parse.urlencode(data).encode(),
        method="POST",
    )
    return opener.open(request).read().decode()


def main() -> None:
    password = os.environ["ADMIN_PASSWORD"]
    username = os.getenv("ADMIN_USERNAME", "admin")
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    health = opener.open(BASE_URL + "/health").read().decode()
    if '"ok"' not in health:
        raise RuntimeError(f"health failed: {health}")
    login_page = opener.open(BASE_URL + "/login").read().decode()
    dashboard = post(
        opener,
        "/login",
        {"username": username, "password": password, "csrf": csrf_from(login_page)},
    )
    if "가격 비교 대시보드" not in dashboard:
        raise RuntimeError("login failed")
    product_pattern = r'href="/products/(\d+)"[^>]*>\s*샤인머스켓'
    product_match = re.search(product_pattern, dashboard)
    if not product_match:
        product_page = post(
            opener,
            "/products",
            {
                "name": "샤인머스켓",
                "keywords": "샤인, shine muscat",
                "csrf": csrf_from(dashboard),
            },
        )
        if "샤인머스켓" not in product_page:
            raise RuntimeError("product creation failed")
        dashboard = opener.open(BASE_URL + "/").read().decode()
        product_match = re.search(product_pattern, dashboard)
    if not product_match:
        position = dashboard.find("샤인머스켓")
        excerpt = dashboard[max(0, position - 120) : position + 120]
        raise RuntimeError(f"created product link not found: {excerpt}")
    product_id = product_match.group(1)
    product_page = opener.open(BASE_URL + f"/products/{product_id}").read().decode()
    post(
        opener,
        f"/products/{product_id}/run",
        {"csrf": csrf_from(product_page)},
    )
    time.sleep(4)
    dashboard = opener.open(BASE_URL + "/").read().decode()
    if "승인된 상품 페이지가 없습니다" not in dashboard:
        raise RuntimeError("worker did not claim and record the comparison job")

    temporary_name = "삭제 기능 스모크 상품"
    temporary_pattern = rf'href="/products/(\d+)"[^>]*>\s*{temporary_name}'
    stale_temporary = re.search(temporary_pattern, dashboard)
    if stale_temporary:
        dashboard = post(
            opener,
            f"/products/{stale_temporary.group(1)}/delete",
            {"csrf": csrf_from(dashboard)},
        )
    temporary_page = post(
        opener,
        "/products",
        {"name": temporary_name, "keywords": "delete smoke", "csrf": csrf_from(dashboard)},
    )
    temporary_id_match = re.search(r"/products/(\d+)/run", temporary_page)
    if not temporary_id_match:
        raise RuntimeError("temporary product creation failed")
    temporary_id = temporary_id_match.group(1)
    scheduled_page = post(
        opener,
        f"/products/{temporary_id}/schedules",
        {
            "cron_expression": "0 9 * * *",
            "timezone": "Asia/Seoul",
            "csrf": csrf_from(temporary_page),
        },
    )
    schedule_match = re.search(rf"/products/{temporary_id}/schedules/(\d+)/delete", scheduled_page)
    if not schedule_match:
        raise RuntimeError("schedule delete control was not rendered")
    schedule_id = schedule_match.group(1)
    after_schedule_delete = post(
        opener,
        f"/products/{temporary_id}/schedules/{schedule_id}/delete",
        {"csrf": csrf_from(scheduled_page)},
    )
    if f"/schedules/{schedule_id}/delete" in after_schedule_delete:
        raise RuntimeError("schedule deletion failed")
    site_id_match = re.search(r'<option value="(\d+)">', after_schedule_delete)
    if site_id_match:
        after_schedule_delete = post(
            opener,
            f"/products/{temporary_id}/sources",
            {
                "site_id": site_id_match.group(1),
                "page_url": "https://partner.choigozip.co.kr/",
                "row_selector": ".smoke-row",
                "name_selector": ".smoke-name",
                "price_selector": ".smoke-price",
                "pre_click_selector": "",
                "csrf": csrf_from(after_schedule_delete),
            },
        )
        if ".smoke-row" not in after_schedule_delete:
            raise RuntimeError("temporary product source creation failed")
    dashboard = post(
        opener,
        f"/products/{temporary_id}/delete",
        {"csrf": csrf_from(after_schedule_delete)},
    )
    if temporary_name in dashboard:
        raise RuntimeError("product deletion failed")

    sites_page = opener.open(BASE_URL + "/sites").read().decode()
    if "사이트·자격증명" not in sites_page:
        raise RuntimeError("admin site access failed")
    if "AdminPlus · hwanggs3" not in sites_page or "최고집 파트너" not in sites_page:
        raise RuntimeError("site quick-registration presets are missing")
    site_match = re.search(r'href="/sites/(\d+)"', sites_page)
    if site_match:
        site_detail = opener.open(BASE_URL + f"/sites/{site_match.group(1)}").read().decode()
        required_detail_markers = ["••••••••••••", "암호화 저장됨 · 수정 불가", "disabled"]
        if not all(marker in site_detail for marker in required_detail_markers):
            raise RuntimeError("site credentials were not rendered as a disabled mask")
        detail_form = BeautifulSoup(site_detail, "html.parser").find(
            "form", attrs={"aria-label": "등록 사이트 상세"}
        )
        if (
            not isinstance(detail_form, Tag)
            or detail_form.get("method")
            or detail_form.get("action")
        ):
            raise RuntimeError("site detail form unexpectedly has a mutation target")
        if any(
            isinstance(control, Tag) and not control.has_attr("disabled")
            for control in detail_form.find_all(["input", "button"])
        ):
            raise RuntimeError("site detail contains an enabled control")
        if "gAAAAA" in site_detail:
            raise RuntimeError("site detail exposed credential ciphertext")
    try:
        post(
            opener,
            "/sites",
            {
                "name": "invalid-smoke-site",
                "domain": "shop.example",
                "catalog_url": "https://shop.example/products",
                "login_url": "https://shop.example/login",
                "username_selector": "",
                "password_selector": "",
                "submit_selector": "",
                "site_username": "incomplete-user",
                "site_password": "",
                "csrf": csrf_from(sites_page),
            },
        )
    except urllib.error.HTTPError as exc:
        validation_body = exc.read().decode()
        if exc.code != 400 or "모두 입력" not in validation_body:
            raise RuntimeError("site validation was not rendered as a useful 400 response") from exc
    else:
        raise RuntimeError("incomplete site configuration was unexpectedly accepted")
    dumped_page = post(opener, "/sites/dump", {"csrf": csrf_from(sites_page)})
    if "DB 덤프 완료" not in dumped_page or "latest.dump" not in dumped_page:
        raise RuntimeError("database dump action failed")
    users_page = opener.open(BASE_URL + "/users").read().decode()
    viewer_password = password
    if "smoke_viewer_v2" not in users_page:
        post(
            opener,
            "/users",
            {
                "username": "smoke_viewer_v2",
                "password": viewer_password,
                "role": "viewer",
                "csrf": csrf_from(users_page),
            },
        )
    viewer = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    viewer_login = viewer.open(BASE_URL + "/login").read().decode()
    viewer_dashboard = post(
        viewer,
        "/login",
        {
            "username": "smoke_viewer_v2",
            "password": viewer_password,
            "csrf": csrf_from(viewer_login),
        },
    )
    if "비교 상품 등록" in viewer_dashboard or "/delete" in viewer_dashboard:
        raise RuntimeError("viewer received admin mutation controls")
    try:
        post(
            viewer,
            f"/products/{product_id}/delete",
            {"csrf": csrf_from(viewer_dashboard)},
        )
    except urllib.error.HTTPError as exc:
        if exc.code != 403:
            raise
    else:
        raise RuntimeError("viewer product deletion was not rejected")
    if site_match:
        try:
            viewer.open(BASE_URL + f"/sites/{site_match.group(1)}")
        except urllib.error.HTTPError as exc:
            if exc.code != 403:
                raise
        else:
            raise RuntimeError("viewer site detail access was not rejected")
    try:
        post(
            viewer,
            "/products",
            {"name": "viewer-must-not-create", "keywords": "", "csrf": csrf_from(viewer_dashboard)},
        )
    except urllib.error.HTTPError as exc:
        if exc.code != 403:
            raise
    else:
        raise RuntimeError("viewer mutation was not rejected")
    print(
        "smoke test passed: health, login, product CRUD, worker queue, "
        "schedule deletion, masked site detail, DB dump, admin access, viewer RBAC"
    )


if __name__ == "__main__":
    main()
