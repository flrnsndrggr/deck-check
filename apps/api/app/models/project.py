from sqlalchemy import String, Integer, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="Untitled Project")
    decklist_text: Mapped[str] = mapped_column(Text)
    bracket: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
