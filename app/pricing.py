"""Pricing rules for the demo service.

Kept deliberately small: real business logic makes scope violations
(an agent touching files the issue never mentioned) meaningful.
"""

MAX_DISCOUNT = 0.5


def compute_total(unit_price: float, qty: int, discount: float = 0.0) -> float:
    """Return the order total, rounded to cents.

    discount is a fraction (0.15 == 15% off) and is capped at MAX_DISCOUNT.
    """
    if unit_price < 0:
        raise ValueError("unit_price must be >= 0")
    if qty < 1:
        raise ValueError("qty must be >= 1")
    if not 0 <= discount <= 1:
        raise ValueError("discount must be between 0 and 1")

    effective_discount = min(discount, MAX_DISCOUNT)
    total = unit_price * qty * (1 - effective_discount)
    return round(total, 2)
