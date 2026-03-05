from sqlalchemy import String, Integer, DateTime, func, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class RunRecord(Base):
    __tablename__ = "run_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seed: Mapped[int] = mapped_column(Integer)
    policy: Mapped[str] = mapped_column(String(64))
    turn_limit: Mapped[int] = mapped_column(Integer)
    bracket: Mapped[int] = mapped_column(Integer)
    template_preset: Mapped[str] = mapped_column(String(64), default="balanced")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
