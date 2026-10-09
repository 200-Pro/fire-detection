"""Bounded trial telemetry: never persist video URLs, API keys, or raw frames."""
import math
import time
from collections import deque
from datetime import timedelta
from sqlalchemy import select
from .models import MonitorTrial, Monitor, TrialEvidence, Alert, AuditLog, utcnow
from .security import aware

class TrialMetrics:
    def __init__(self, previous=None):
        self.totals = dict(previous or {})
        self.last_frame = None
        self.samples = {key: deque(maxlen=500) for key in ("cycle_ms", "decode_wait_ms", "frame_interval_ms")}

    def add(self, key, value=1):
        self.totals[key] = self.totals.get(key, 0) + value

    def observe(self, key, value):
        self.samples[key].append(float(value))
        self.totals[key + "_count"] = self.totals.get(key + "_count", 0) + 1
        self.totals[key + "_sum"] = self.totals.get(key + "_sum", 0) + value
        self.totals[key + "_max"] = max(self.totals.get(key + "_max", 0), value)

    def frame(self):
        now = time.monotonic()
        if self.last_frame is not None:
            self.observe("frame_interval_ms", (now-self.last_frame)*1000)
        self.last_frame = now
        self.add("frames")

    def report(self):
        result = dict(self.totals)
        for key, samples in self.samples.items():
            count = self.totals.get(key + "_count", 0)
            result[key + "_mean"] = self.totals.get(key + "_sum", 0)/count if count else None
            ordered = sorted(samples)
            result[key + "_recent_p95"] = ordered[max(0, math.ceil(len(ordered)*.95)-1)] if ordered else None
        result["p95_scope"] = "up to 500 samples since current worker start; means/max/counters cumulative"
        result["accuracy_validated"] = False
        return result

def active_trial(db, camera_id, revision):
    return db.scalar(select(MonitorTrial).where(MonitorTrial.camera_id==camera_id,
        MonitorTrial.revision==revision, MonitorTrial.state=="running"))

def expire_trials(sessions, reports):
    """Persist aggregate counters and enforce wall-clock deadlines across restart."""
    with sessions() as db:
        for trial in db.scalars(select(MonitorTrial).where(MonitorTrial.state=="running")):
            m = db.get(Monitor, trial.camera_id)
            current = reports.get(trial.camera_id)
            if current and current["revision"] == trial.revision:
                trial.report = current["report"]
            if not m or not m.enabled or m.revision != trial.revision:
                trial.state = "stopped"
            elif aware(trial.deadline) <= utcnow():
                m.enabled = False
                m.revision += 1
                trial.state = "completed"
                db.add(AuditLog(owner_id=trial.owner_id, action="monitor.trial_expired", target_id=trial.id))
            if trial.state != "running":
                trial.ended_at = utcnow()
        db.commit()

def register_evidence(sessions, monitor, event):
    if not event.get("snapshot_url"):
        return
    with sessions() as db:
        trial = db.scalar(select(MonitorTrial).where(MonitorTrial.camera_id==monitor.camera_id,
            MonitorTrial.revision==monitor.revision).order_by(MonitorTrial.started_at.desc()))
        if trial and not db.get(TrialEvidence, event["id"]):
            db.add(TrialEvidence(alert_id=event["id"], trial_id=trial.id,
                expires_at=utcnow()+timedelta(hours=trial.evidence_hours)))
            db.commit()

def cleanup_evidence(sessions, store):
    """Delete only individually enrolled NEW trial snapshots; retain alarm metadata."""
    deleted = 0
    with sessions() as db:
        rows = list(db.scalars(select(TrialEvidence).where(TrialEvidence.deleted_at.is_(None),
            TrialEvidence.expires_at <= utcnow()).limit(100)))
        for row in rows:
            alert = db.get(Alert, row.alert_id)
            if alert and alert.snapshot_key:
                # Exact application-generated object only, never a directory/glob.
                if alert.snapshot_key != f"alerts/{alert.id}.jpg":
                    continue
                try:
                    store.delete(alert.snapshot_key)
                except (OSError, ValueError):
                    continue  # Retry later. Never report successful deletion on failure.
                alert.snapshot_key = None
                db.add(AuditLog(owner_id=alert.owner_id, action="evidence.trial_expired", target_id=alert.id))
            row.deleted_at = utcnow()
            deleted += 1
        db.commit()
    return deleted
