"""SQLite repository (local/test). Cloud uses a Firestore implementation behind
the same small interface. Orders are idempotent on dedupe_key."""

from __future__ import annotations

import json
from typing import Protocol

from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, insert, select
from sqlalchemy.exc import IntegrityError

from fxlab.schemas import Decision, TradeProposal


class Repository(Protocol):
    def save_decision(self, d: Decision) -> None: ...
    def save_order_once(self, p: TradeProposal, decision_id: str) -> bool: ...
    def decisions(self) -> list[dict]: ...


_md = MetaData()
_decisions = Table("decisions", _md, Column("decision_id", String, primary_key=True),
                   Column("decision", String), Column("symbol", String), Column("data_ts", String),
                   Column("config_version", String), Column("payload", Text))
_orders = Table("orders", _md, Column("dedupe_key", String, primary_key=True),
                Column("decision_id", String), Column("payload", Text))
SCHEMA_VERSION = 1


class SqliteRepository:
    def __init__(self, url: str = "sqlite://"):
        self.engine = create_engine(url)
        _md.create_all(self.engine)

    def save_decision(self, d: Decision) -> None:
        row = dict(decision_id=d.decision_id, decision=d.decision.value, symbol=d.symbol,
                   data_ts=d.data_ts.isoformat(), config_version=d.config_version,
                   payload=d.model_dump_json())
        with self.engine.begin() as cx:
            try:
                cx.execute(insert(_decisions).values(**row))
            except IntegrityError:
                pass  # re-processing the same decision is a no-op (restart-safe)

    def save_order_once(self, p: TradeProposal, decision_id: str) -> bool:
        with self.engine.begin() as cx:
            try:
                cx.execute(insert(_orders).values(dedupe_key=p.dedupe_key, decision_id=decision_id,
                                                  payload=p.model_dump_json()))
                return True
            except IntegrityError:
                return False

    def decisions(self) -> list[dict]:
        with self.engine.connect() as cx:
            return [json.loads(r.payload) for r in cx.execute(select(_decisions))]
