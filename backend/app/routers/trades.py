"""Router: trades."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.trade import TradeCostCreate, TradeCostRead, TradeCreate, TradeRead
from app.services.trade_service import TradeService

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("", response_model=list[TradeRead])
def list_trades(
    security_id: int | None = Query(default=None),
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db, scope="function"),
):
    return TradeService(db).list_trades_with_costs(security_id=security_id, account_id=account_id)


@router.post("", response_model=TradeRead, status_code=201)
def create_trade(payload: TradeCreate, db: Session = Depends(get_db, scope="function")):
    return TradeService(db).create_trade(payload)


@router.get("/{id}", response_model=TradeRead)
def get_trade(id: int, db: Session = Depends(get_db, scope="function")):
    service = TradeService(db)
    return service.to_read_with_costs(service.get_trade(id))


@router.delete("/{id}", status_code=204)
def delete_trade(id: int, db: Session = Depends(get_db, scope="function")):
    TradeService(db).delete_trade(id)


@router.post("/{id}/costs", response_model=TradeCostRead, status_code=201)
def add_trade_cost(
    id: int, payload: TradeCostCreate, db: Session = Depends(get_db, scope="function")
):
    return TradeService(db).add_cost(id, payload)


@router.get("/{id}/costs", response_model=list[TradeCostRead])
def list_trade_costs(id: int, db: Session = Depends(get_db, scope="function")):
    return TradeService(db).list_costs(id)


@router.delete("/{id}/costs/{cost_id}", status_code=204)
def delete_trade_cost(id: int, cost_id: int, db: Session = Depends(get_db, scope="function")):
    TradeService(db).delete_cost(id, cost_id)
