"""
Server-side price calculation. Mirrors the checkout breakdown in
frontend/src/pages/Checkout.tsx so the client never decides what a booking costs.
"""

from dataclasses import dataclass

TAX_RATE = 0.12
AI_DISCOUNT = 1500  # flat BDT discount shown as "AI deal" at checkout

ADDON_PRICES = {
    'transfer': 1200,
    'jeep': 4500,
    'tour': 800,
    'spa': 1500,
}

COUPONS = {
    'LUMINA20': 0.10,  # extra 10% off the grand total
}


@dataclass(frozen=True)
class PriceBreakdown:
    nights: int
    room_total: int
    tax: int
    addons_total: int
    discount: int
    total: int


def calculate_price(price_per_night: int, nights: int, room_count: int = 1,
                    addons: list[str] | None = None, coupon: str = '') -> PriceBreakdown:
    room_total = price_per_night * nights * room_count
    tax = round(room_total * TAX_RATE)
    addons_total = sum(ADDON_PRICES[a] for a in (addons or []))
    grand_total = max(room_total + tax + addons_total - AI_DISCOUNT, 0)

    coupon_rate = COUPONS.get(coupon.strip().upper(), 0) if coupon else 0
    total = round(grand_total * (1 - coupon_rate))

    return PriceBreakdown(
        nights=nights,
        room_total=room_total,
        tax=tax,
        addons_total=addons_total,
        discount=AI_DISCOUNT + (grand_total - total),
        total=total,
    )
