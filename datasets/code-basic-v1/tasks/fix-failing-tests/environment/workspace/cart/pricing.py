"""价格工具。所有金额以整数「分」表示。"""


def apply_discount(price_cents: int, percent: int) -> int:
    """返回打折后的价格（分）。percent 为 0 到 100 的折扣百分比，结果向下取整。

    例如 apply_discount(1000, 20) == 800。percent 超出 0 到 100 时抛出 ValueError。
    """
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    return price_cents * percent // 100


def format_price(price_cents: int) -> str:
    """把分格式化为美元字符串，小数部分固定两位，例如 1205 -> "$12.05"。"""
    return f"${price_cents // 100}.{price_cents % 100}"
