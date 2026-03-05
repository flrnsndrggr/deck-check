from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScryfallCard(Base):
    __tablename__ = "scryfall_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    oracle_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ScryfallName(Base):
    __tablename__ = "scryfall_names"

    name: Mapped[str] = mapped_column(String(300), primary_key=True)
    oracle_id: Mapped[str] = mapped_column(String(64), ForeignKey("scryfall_cards.oracle_id", ondelete="CASCADE"), index=True)


class ScryfallRuling(Base):
    __tablename__ = "scryfall_rulings"

    oracle_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
