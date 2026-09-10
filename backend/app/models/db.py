"""SQLAlchemy ORM models matching .freebuff/11_DATABASE_DESIGN.md."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repository: Mapped[str] = mapped_column(String(200), index=True)
    issue_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True, default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    fatal_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    events: Mapped[list["ExecutionEvent"]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="ExecutionEvent.sequence",
    )
    report: Mapped["ResolutionReport | None"] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", uselist=False
    )
    approvals: Mapped[list["Approval"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_analyses_created_at", "created_at"),
    )


class ExecutionEvent(Base):
    __tablename__ = "execution_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64))
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    analysis: Mapped[Analysis] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_execution_events_analysis_seq", "analysis_id", "sequence"),
    )


class ResolutionReport(Base):
    __tablename__ = "resolution_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    issue_summary: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(200))
    priority: Mapped[str] = mapped_column(String(32))
    root_cause: Mapped[str] = mapped_column(Text)
    confidence: Mapped[int] = mapped_column(Integer)  # stored as 0..100
    resolution_plan_json: Mapped[list] = mapped_column(JSON)
    affected_files_json: Mapped[list] = mapped_column(JSON)
    test_plan_json: Mapped[list] = mapped_column(JSON)
    evidence_json: Mapped[list] = mapped_column(JSON, default=list)
    warnings_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    analysis: Mapped[Analysis] = relationship(back_populates="report")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    action_type: Mapped[str] = mapped_column(String(64))
    action_payload_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|approved|rejected|failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    analysis: Mapped[Analysis] = relationship(back_populates="approvals")