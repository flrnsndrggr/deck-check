from sqlalchemy import String, Integer, Text, DateTime, func, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProjectVersion(Base):
    __tablename__ = "project_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200), default="Untitled Project")
    deck_name: Mapped[str] = mapped_column(String(200), default="Untitled Deck")
    commander_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decklist_text: Mapped[str] = mapped_column(Text)
    bracket: Mapped[int] = mapped_column(Integer, default=3)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    saved_bundle: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
