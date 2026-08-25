import pytest

from app.scraping import (
    credential_request_allowed,
    validate_login_configuration,
    validate_login_url,
)


def test_credentials_require_https_login_url():
    with pytest.raises(ValueError, match="HTTPS"):
        validate_login_url("http://shop.example/login", "shop.example", True)


def test_anonymous_site_can_use_http_for_local_development():
    assert validate_login_url("http://shop.example/login", "shop.example", False).startswith(
        "http://"
    )


def test_credential_requests_are_confined_to_registered_domain():
    assert credential_request_allowed("https://shop.example/session", "shop.example")
    assert credential_request_allowed("wss://shop.example/socket", "shop.example")
    assert not credential_request_allowed("https://auth.shop.example/session", "shop.example")
    assert not credential_request_allowed("https://evil.example/collect", "shop.example")
    assert not credential_request_allowed("http://shop.example/login", "shop.example")


def test_partial_login_configuration_is_rejected():
    with pytest.raises(ValueError, match="로그인 URL"):
        validate_login_configuration("", "user", "password", "#user", "#pass", "button")
    with pytest.raises(ValueError, match="모두 입력"):
        validate_login_configuration(
            "https://shop.example/login", "user", "", "#user", "#pass", "button"
        )
