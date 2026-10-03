"""SQLite data models for loopprism traces and spans."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, relationship


class Base(DeclarativeBase):
    pass


class Trace(Base):
    """A single Agent interaction — a group of related spans."""

    __tablename__ = "traces"

    id: Mapped[str] = Column(String(36), primary_key=True)
    conversation_id: Mapped[Optional[str]] = Column(String(64), nullable=True)
    timestamp: Mapped[datetime] = Column(DateTime, default=datetime.utcnow)

    # Root span details
    root_span_type: Mapped[Optional[str]] = Column(String(32), nullable=True)
    root_span_name: Mapped[Optional[str]] = Column(String(128), nullable=True)

    # Summary stats (computed after trace completes)
    total_latency_ms: Mapped[Optional[float]] = Column(Float, nullable=True)
    total_cost_usd: Mapped[Optional[float]] = Column(Float, nullable=True)
    span_count: Mapped[int] = Column(Integer, default=0)
    error_count: Mapped[int] = Column(Integer, default=0)

    # Which MCP servers were involved (JSON array string)
    mcp_servers: Mapped[Optional[str]] = Column(Text, nullable=True)

    # User-defined tags (JSON string)
    tags: Mapped[Optional[str]] = Column(Text, nullable=True)

    # Extra metadata (JSON string)
    trace_metadata: Mapped[Optional[str]] = Column(
        "metadata",
        Text,
        nullable=True,
    )

    spans: Mapped[list["Span"]] = relationship(
        "Span",
        back_populates="trace",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Trace id={self.id} spans={self.span_count} "
            f"cost=${self.total_cost_usd}>"
        )


class Span(Base):
    """A single operation within a trace — e.g. one MCP tool call."""

    __tablename__ = "spans"

    id: Mapped[str] = Column(String(36), primary_key=True)
    trace_id: Mapped[str] = Column(
        String(36),
        ForeignKey("traces.id", ondelete="CASCADE"),
    )
    parent_span_id: Mapped[Optional[str]] = Column(
        String(36),
        nullable=True,
    )

    # Span classification
    span_type: Mapped[str] = Column(
        String(32),
        default="generic",
    )  # "mcp.tool.call", "mcp.server.list_tools", etc.

    # Timing
    start_time: Mapped[datetime] = Column(DateTime, default=datetime.utcnow)
    end_time: Mapped[Optional[datetime]] = Column(DateTime, nullable=True)
    latency_ms: Mapped[Optional[float]] = Column(Float, nullable=True)

    # ---- MCP-specific fields ----
    mcp_server_name: Mapped[Optional[str]] = Column(String(128), nullable=True)
    mcp_server_version: Mapped[Optional[str]] = Column(
        String(32),
        nullable=True,
    )
    mcp_transport: Mapped[Optional[str]] = Column(
        String(16),
        nullable=True,
    )  # "http", "stdio", "sse"
    mcp_request_method: Mapped[Optional[str]] = Column(
        String(64),
        nullable=True,
    )  # "tools/call", "tools/list", etc.
    mcp_request_id: Mapped[Optional[str]] = Column(
        String(36),
        nullable=True,
    )  # JSON-RPC id

    # ---- Tool-specific fields (span_type = "mcp.tool.call") ----
    tool_name: Mapped[Optional[str]] = Column(String(256), nullable=True)
    tool_arguments: Mapped[Optional[str]] = Column(Text, nullable=True)
    tool_call_id: Mapped[Optional[str]] = Column(String(64), nullable=True)

    # ---- Result fields ----
    result_content_preview: Mapped[Optional[str]] = Column(
        Text,
        nullable=True,
    )  # First 500 chars
    result_size_bytes: Mapped[Optional[int]] = Column(Integer, nullable=True)
    result_is_error: Mapped[bool] = Column(Integer, default=False)

    # ---- LLM association ----
    upstream_llm_tokens: Mapped[Optional[int]] = Column(
        Integer,
        nullable=True,
    )
    downstream_llm_tokens: Mapped[Optional[int]] = Column(
        Integer,
        nullable=True,
    )

    # ---- Metadata ----
    attributes_json: Mapped[Optional[str]] = Column(
        Text,
        nullable=True,
    )  # Arbitrary JSON key-value
    status: Mapped[str] = Column(String(16), default="ok")  # "ok" | "error"

    # Relationship
    trace: Mapped["Trace"] = relationship("Trace", back_populates="spans")

    def __repr__(self) -> str:
        return (
            f"<Span id={self.id} type={self.span_type} "
            f"tool={self.tool_name} latency={self.latency_ms}ms>"
        )
