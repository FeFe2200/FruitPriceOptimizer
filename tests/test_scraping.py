from decimal import Decimal

import pytest

from app.scraping import extract_prices


def test_extract_prices_from_repeated_option_rows():
    html = """
    <div class='option'><span class='name'>1kg 2수</span><span class='price'>8,750원</span></div>
    <div class='option'><span class='name'>2kg 5수</span><span class='price'>11,350원</span></div>
    """

    rows = extract_prices(
        html,
        row_selector=".option",
        name_selector=".name",
        price_selector=".price",
    )

    assert rows == [
        ("1kg 2수", Decimal("8750")),
        ("2kg 5수", Decimal("11350")),
    ]


def test_extract_prices_rejects_missing_rows():
    with pytest.raises(ValueError, match="가격 행을 찾지 못했습니다"):
        extract_prices("<html></html>", ".option", ".name", ".price")
