from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Float, Integer, DateTime, ForeignKey, JSON, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def utcnow():
    return datetime.now(timezone.utc)

def uid():
    return uuid4().hex

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))

class LoginSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    location: Mapped[str] = mapped_column(String(100), default="")
    kind: Mapped[str] = mapped_column(String(20), default="browser")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_signal: Mapped[str] = mapped_column(String(20), default="offline")
    frames: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    publisher_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    publisher_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pair_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    pair_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"), index=True)
    camera_name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20), default="live")
    state: Mapped[str] = mapped_column(String(20), default="new", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    model_sha256: Mapped[str] = mapped_column(String(64))
    policy_sha256: Mapped[str] = mapped_column(String(64))
    snapshot_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detections: Mapped[list] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(Text, default="")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Monitor(Base):
    __tablename__ = "cctv_monitors"
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    catalog_id: Mapped[str] = mapped_column(String(24))
    road: Mapped[str] = mapped_column(String(8))
    video_type: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_reference: Mapped[str] = mapped_column(String(300), default="")
    interval_seconds: Mapped[float] = mapped_column(Float, default=3)
    rules: Mapped[dict] = mapped_column(JSON, default=dict)
    calibration: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    auto_spread: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class IncidentLocation(Base):
    __tablename__ = "incident_locations"
    event_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    estimate: Mapped[dict] = mapped_column(JSON)
    simulation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="estimated")
    message: Mapped[str] = mapped_column(String(300), default="")

class AlertReview(Base):
    __tablename__ = "alert_reviews"
    event_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(300), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class MonitorTrial(Base):
    __tablename__ = "monitor_trials"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="running", index=True)
    evidence_hours: Mapped[int] = mapped_column(Integer, default=24)
    report: Mapped[dict] = mapped_column(JSON, default=dict)

class TrialEvidence(Base):
    __tablename__ = "trial_evidence_expiry"
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), primary_key=True)
    trial_id: Mapped[str] = mapped_column(ForeignKey("monitor_trials.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
