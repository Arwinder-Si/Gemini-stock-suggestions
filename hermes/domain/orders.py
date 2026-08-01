"""
Order domain models and state machine enumeration.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal
import uuid
from hermes.clock import now_ist


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL_M"


class OrderState(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    symbol: str
    security_id: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: float = 0.0
    trigger_price: float = 0.0
    client_order_id: str = field(default_factory=lambda: f"ORD-{uuid.uuid4().hex[:12].upper()}")
    broker_order_id: str | None = None
    state: OrderState = OrderState.PENDING
    filled_quantity: int = 0
    average_fill_price: float = 0.0
    rejection_reason: str | None = None
    created_at: str = field(default_factory=lambda: now_ist().strftime("%Y-%m-%d %H:%M:%S IST"))
    updated_at: str = field(default_factory=lambda: now_ist().strftime("%Y-%m-%d %H:%M:%S IST"))
