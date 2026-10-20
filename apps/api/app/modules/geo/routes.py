"""Autocomplete de endereço (Photon + ViaCEP) para quem cadastra e edita estações."""
from fastapi import APIRouter, Depends, Query

from ...database import db_session
from ...errors import fail
from ...security import current_user
from ..auth.routes import limit
from .service import ATTRIBUTION, suggestions

router = APIRouter()

# Busca enquanto digita (com espera de ~350 ms no cliente): folga para digitação rápida, sem abuso.
SUGGEST_LIMIT = (60, 60)


@router.get("/geo/address-suggestions")
def address_suggestions(q: str = Query(min_length=1, max_length=120), lat: float | None = Query(None, ge=-90, le=90),
                        lng: float | None = Query(None, ge=-180, le=180), user=Depends(current_user),
                        db=Depends(db_session)):
    if (lat is None) != (lng is None):
        fail("coordinates_required", "Informe lat e lng juntos", 422)
    limit(db, f"geo-suggest:{user.id}", maximum=SUGGEST_LIMIT[0], seconds=SUGGEST_LIMIT[1])
    items, available = suggestions(q, lat, lng)
    return {"items": items, "available": available, "attribution": ATTRIBUTION}
