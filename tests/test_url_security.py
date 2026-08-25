import pytest

from app.scraping import validate_scrape_url


def test_scrape_url_must_match_registered_domain():
    with pytest.raises(ValueError, match="등록된 도메인"):
        validate_scrape_url("https://evil.example/product", "shop.example")


def test_scrape_url_rejects_localhost_and_private_hosts():
    for url in ["http://localhost:8000", "http://127.0.0.1", "http://169.254.169.254"]:
        with pytest.raises(ValueError, match="내부 네트워크"):
            validate_scrape_url(url, None)


def test_scrape_url_accepts_registered_https_domain():
    assert validate_scrape_url("https://shop.example/products/1", "shop.example") == (
        "https://shop.example/products/1"
    )


def test_scrape_url_rejects_unregistered_subdomain():
    with pytest.raises(ValueError, match="등록된 도메인"):
        validate_scrape_url("https://cdn.shop.example/products/1", "shop.example")
