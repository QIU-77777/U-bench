from .pricing import apply_discount


class Cart:
    """购物车：记录商品单价（分）与数量。"""

    def __init__(self):
        self._items = {}

    def add(self, name: str, price_cents: int, qty: int = 1) -> None:
        """加入商品。同名商品再次加入时数量累加。qty 小于 1 时抛出 ValueError。"""
        if qty < 1:
            raise ValueError("qty must be at least 1")
        old_qty = self._items[name][1] if name in self._items else 0
        self._items[name] = (price_cents, old_qty + qty)

    def remove(self, name: str) -> None:
        """移除商品。商品不存在时抛出 KeyError。"""
        del self._items[name]

    def quantity(self, name: str) -> int:
        """返回商品数量，不存在时返回 0。"""
        return self._items[name][1] if name in self._items else 0

    def total_cents(self, discount_percent: int = 0) -> int:
        """返回整车总价（分）：先求和，再整体打折。"""
        subtotal = sum(price * qty for price, qty in self._items.values())
        return apply_discount(subtotal, discount_percent)
