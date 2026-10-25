import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.pricing import compute_total

app = FastAPI(title="IntentLock Demo Service")

VERSION = os.getenv("APP_VERSION", "dev")


class PriceRequest(BaseModel):
    unit_price: float
    qty: int
    discount: float = 0.0


@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION}


@app.post("/price")
def price(req: PriceRequest):
    try:
        total = compute_total(req.unit_price, req.qty, req.discount)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"total": total}
