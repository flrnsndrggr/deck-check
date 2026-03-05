from sqlalchemy import String, Integer, DateTime, func, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class DataSourceStatus(Base):
    __tablename__ = "data_source_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    source_url: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(128), default="")
    warning: Mapped[str] = mapped_column(Text, default="")
    last_fetched_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
