import pytest

from cart import Cart, apply_discount, format_price


def test_apply_discount_basic():
    assert apply_discount(1000, 20) == 800


def test_apply_discount_invalid_percent():
    with pytest.raises(ValueError):
        apply_discount(1000, 120)


def test_format_price_pads_cents():
    assert format_price(1205) == "$12.05"
    assert format_price(1210) == "$12.10"


def test_add_accumulates_quantity():
    cart = Cart()
    cart.add("pen", 150, 2)
    cart.add("pen", 150, 3)
    assert cart.quantity("pen") == 5


def test_total_with_discount():
    cart = Cart()
    cart.add("pen", 150, 2)
    cart.add("book", 1000)
    assert cart.total_cents() == 1300
    assert cart.total_cents(discount_percent=10) == 1170


def test_remove_missing_raises():
    with pytest.raises(KeyError):
        Cart().remove("nothing")
