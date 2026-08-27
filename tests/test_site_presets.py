from app.site_presets import SITE_PRESETS


def test_adminplus_preset_matches_hwanggs3_login_and_catalog():
    preset = SITE_PRESETS["adminplus-hwanggs3"]

    assert preset["domain"] == "hwanggs3.adminplus.co.kr"
    assert preset["catalog_url"].endswith("/?mod=product&actpage=prt.list")
    assert preset["login_url"].endswith("/partner/login.html")
    assert preset["username_selector"] == "#memid"
    assert preset["password_selector"] == "#admpwd"  # noqa: S105
    assert preset["submit_selector"] == "#loginBtn"
    assert preset["login_pre_click_selector"] == ""


def test_choigozip_preset_opens_login_modal_before_filling_credentials():
    preset = SITE_PRESETS["choigozip"]

    assert preset["domain"] == "partner.choigozip.co.kr"
    assert preset["username_selector"] == "#login-modal-id"
    assert preset["password_selector"] == "#login-modal-pw"  # noqa: S105
    assert preset["submit_selector"] == 'form button[type="submit"]'
    assert preset["login_pre_click_selector"] == "text=로그인"
