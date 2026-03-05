from sqlalchemy import String, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class RulesReference(Base):
    __tablename__ = "rules_references"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
