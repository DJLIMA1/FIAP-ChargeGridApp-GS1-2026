"""Account context shared by the app and the kiosk. Wallet amounts are simulation only.

Device authentication never implies access to an account. The short-lived user JWT
is checked independently on every account request and is never persisted by the panel.
"""
from decimal import Decimal

from fastapi import Depends, Header
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from chargegrid_core.driver import default_profile, presets, validate_profile
from chargegrid_core.driver.vehicles import vehicle_from_dict

from ...database import db_session
from ...errors import fail
from ...models import DriverProfile, Profile, SimulatedWallet, now
from ...schemas import Input
from ...security import current_user


def kiosk_user(x_kiosk_authorization: str = Header(default=""), db=Depends(db_session)):
    return current_user(x_kiosk_authorization, db) if x_kiosk_authorization else None


def wallet(db, user, *, lock=False):
    # Same lock order as start/payment: profile -> connector -> payment.
    if lock:
        db.scalar(select(Profile).where(Profile.id == user.id).with_for_update())
    db.execute(insert(SimulatedWallet).values(user_id=user.id, balance_cents=0, transactions=[])
               .on_conflict_do_nothing())
    query = select(SimulatedWallet).where(SimulatedWallet.user_id == user.id)
    return db.scalar(query.execution_options(populate_existing=True))


def wallet_view(obj):
    return {"balance": f"{Decimal(obj.balance_cents) / 100:.2f}", "simulated": True,
            "legacy_imported": obj.legacy_imported, "transactions": obj.transactions[-100:]}


def move(db, user, cents, title, key):
    obj = wallet(db, user, lock=True)
    for item in obj.transactions:
        if item.get("key") == key:
            if item["signed_cents"] != cents:
                fail("idempotency_conflict", "Esta operação já foi usada com outro valor", 409)
            return obj
    if obj.balance_cents + cents < 0:
        fail("insufficient_balance", "Saldo simulado insuficiente. Escolha Pix ou cartão.", 402)
    obj.balance_cents += cents
    obj.transactions = [*obj.transactions, {"key": key, "signed_cents": cents,
        "kind": "credit" if cents > 0 else "debit", "title": title,
        "amount": f"{Decimal(abs(cents)) / 100:.2f}", "created_at": now().isoformat()}]
    db.flush()
    return obj


def vehicle_view(db, user):
    saved = db.get(DriverProfile, user.id)
    try:
        profile = validate_profile({"vehicle": saved.vehicle, "preferences": saved.preferences}) if saved else None
    except ValueError:
        profile = None
    result = profile or validate_profile(default_profile())
    return {**result, "vehicle": vehicle_from_dict(result["vehicle"]).to_dict(), "saved": profile is not None,
            "presets": presets()}


def context(db, user):
    vehicle = vehicle_view(db, user)
    return {"name": user.name, "vehicle": vehicle["vehicle"] if vehicle["saved"] else None,
            "wallet": wallet_view(wallet(db, user))}


class WalletMove(Input):
    kind: str = Field(pattern=r"^(credit|debit|import)$")
    amount: Decimal = Field(ge=0, le=100000, decimal_places=2, allow_inf_nan=False)
    title: str = Field(default="Saldo de apresentação", max_length=100)


def simulate_move(db, user, data, key):
    if not key or len(key) > 100:
        fail("idempotency_key_required", "Identifique a operação", 422)
    # This ledger is explicitly simulated, including outside presentation mode.
    # It can only fund kiosk sessions at presentation stations, never Stripe.
    cents = int(data.amount * 100)
    obj = wallet(db, user, lock=True)
    if data.kind == "import":
        if obj.legacy_imported:
            return wallet_view(obj)
        obj.legacy_imported = True
        if cents:
            move(db, user, cents, "Saldo simulado importado do aplicativo", "legacy-import")
    else:
        move(db, user, cents if data.kind == "credit" else -cents, data.title, key)
    return wallet_view(obj)
