import pytest

from cart import Cart, apply_discount, format_price


def test_discount_basic():
    assert apply_discount(1000, 20) == 800


def test_discount_zero_and_full():
    assert apply_discount(999, 0) == 999
    assert apply_discount(999, 100) == 0


def test_discount_rounds_down():
    assert apply_discount(999, 10) == 899


def test_discount_invalid_percent():
    with pytest.raises(ValueError):
        apply_discount(1000, -1)
    with pytest.raises(ValueError):
        apply_discount(1000, 101)


def test_format_price_pads_cents():
    assert format_price(1205) == "$12.05"
    assert format_price(1210) == "$12.10"


def test_format_price_edges():
    assert format_price(0) == "$0.00"
    assert format_price(5) == "$0.05"
    assert format_price(100000) == "$1000.00"


def test_add_accumulates_quantity():
    cart = Cart()
    cart.add("pen", 150, 2)
    cart.add("pen", 150, 3)
    assert cart.quantity("pen") == 5


def test_add_default_quantity_accumulates():
    cart = Cart()
    cart.add("pen", 150)
    cart.add("pen", 150)
    assert cart.quantity("pen") == 2


def test_add_invalid_qty():
    cart = Cart()
    with pytest.raises(ValueError):
        cart.add("pen", 150, 0)
    assert cart.quantity("pen") == 0


def test_total_with_discount():
    cart = Cart()
    cart.add("pen", 150, 2)
    cart.add("book", 1000)
    assert cart.total_cents() == 1300
    assert cart.total_cents(discount_percent=10) == 1170


def test_total_empty_cart():
    assert Cart().total_cents() == 0
    assert Cart().total_cents(discount_percent=50) == 0


def test_total_after_repeated_add_and_remove():
    cart = Cart()
    cart.add("pen", 150)
    cart.add("pen", 150)
    cart.add("book", 1000)
    cart.remove("book")
    assert cart.total_cents() == 300
    assert cart.quantity("book") == 0


def test_remove_missing_raises():
    with pytest.raises(KeyError):
        Cart().remove("nothing")
