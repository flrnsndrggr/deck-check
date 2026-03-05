from sqlalchemy import String, Integer, DateTime, func, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class SimJob(Base):
    __tablename__ = "sim_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
