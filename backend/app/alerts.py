"""Temporal confirmation is a demo heuristic, not a validated incident detector."""
from collections import deque
from dataclasses import dataclass, field
from copy import deepcopy
from threading import RLock

@dataclass
class SignalState:
    history: deque = field(default_factory=deque)
    last_frame: float | None = None
    last_alarm: float = -1e12
    latched: bool = False
    clear_frames: int = 0

class AlarmGate:
    def __init__(self, settings):
        self.settings = settings
        self.states = {}
        self.lock = RLock()

    def reset(self, camera_id):
        with self.lock:
            self.states.pop(camera_id, None)
            self.states.pop(camera_id+':smoke', None)

    def propose(self, camera_id, fire, now):
        """Compute without latching an alarm until its database commit succeeds."""
        with self.lock:
            state = deepcopy(self.states.get(camera_id, SignalState()))
            return state, self._observe(state, fire, now)

    def commit(self, camera_id, state):
        with self.lock:
            self.states[camera_id] = state

    def observe(self, camera_id, fire, now):
        with self.lock:
            state, decision = self.propose(camera_id, fire, now)
            self.commit(camera_id, state)
            return decision

    def _observe(self, s, fire, now):
        cfg = self.settings
        if s.last_frame is not None and now-s.last_frame > cfg.frame_gap_seconds:
            s.history.clear()
            s.clear_frames = 0
            s.latched = False
        s.last_frame = now
        s.history.append((now, fire))
        while len(s.history) > cfg.alarm_window:
            s.history.popleft()
        s.clear_frames = 0 if fire else s.clear_frames + 1
        if s.clear_frames >= cfg.alarm_clear_frames:
            s.latched = False
        hits = [t for t, positive in s.history if positive]
        confirmed = (fire and len(hits) >= cfg.alarm_hits and hits[-1]-hits[0] >= cfg.alarm_min_seconds)
        trigger = confirmed and not s.latched and now-s.last_alarm >= cfg.alarm_cooldown_seconds
        if trigger:
            s.latched = True
            s.last_alarm = now
        return {"trigger": bool(trigger), "hits": len(hits), "required": cfg.alarm_hits,
                "signal": "fire" if fire else "clear", "latched": s.latched}
