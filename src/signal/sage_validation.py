from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Literal

import numpy as np

TrackClass = Literal["validated_mpc", "short_lived", "unstable_candidate"]


@dataclass(frozen=True)
class SageCandidate:
    file: str
    window_index: int
    time_sec: float
    candidate_id: int
    delay_ns: float
    doppler_hz: float
    power_db: float
    score_db: float
    source_kind: str = "final"


@dataclass
class SageTrack:
    track_id: int
    candidates: list[SageCandidate] = field(default_factory=list)
    classification: TrackClass = "short_lived"
    reject_reason: str = ""

    @property
    def length_windows(self) -> int:
        return len({c.window_index for c in self.candidates})

    @property
    def start_window(self) -> int:
        return min(c.window_index for c in self.candidates)

    @property
    def end_window(self) -> int:
        return max(c.window_index for c in self.candidates)

    @property
    def delay_median_ns(self) -> float:
        return float(median(c.delay_ns for c in self.candidates))

    @property
    def delay_std_ns(self) -> float:
        return float(np.std([c.delay_ns for c in self.candidates]))

    @property
    def doppler_median_hz(self) -> float:
        return float(median(c.doppler_hz for c in self.candidates))

    @property
    def doppler_std_hz(self) -> float:
        return float(np.std([c.doppler_hz for c in self.candidates]))

    @property
    def power_median_db(self) -> float:
        return float(median(c.power_db for c in self.candidates))

    @property
    def power_max_db(self) -> float:
        return float(max(c.power_db for c in self.candidates))


@dataclass
class SageValidationResult:
    tracks: list[SageTrack]

    @property
    def validated_tracks(self) -> list[SageTrack]:
        return [t for t in self.tracks if t.classification == "validated_mpc"]

    @property
    def rejected_tracks(self) -> list[SageTrack]:
        return [t for t in self.tracks if t.classification != "validated_mpc"]


def _candidate_distance(
    previous: SageCandidate,
    current: SageCandidate,
    *,
    delay_gate_ns: float,
    doppler_gate_hz: float,
) -> float | None:
    delay_delta = abs(current.delay_ns - previous.delay_ns)
    doppler_delta = abs(current.doppler_hz - previous.doppler_hz)
    if delay_delta > delay_gate_ns or doppler_delta > doppler_gate_hz:
        return None
    delay_scale = max(float(delay_gate_ns), 1e-12)
    doppler_scale = max(float(doppler_gate_hz), 1e-12)
    # Prefer close delay/Doppler, then stronger candidates when ties occur.
    return delay_delta / delay_scale + doppler_delta / doppler_scale - 1e-4 * current.power_db


def _classify_track(
    track: SageTrack,
    *,
    min_track_length: int,
    max_delay_std_ns: float | None,
    max_doppler_std_hz: float | None,
) -> None:
    if track.length_windows < int(min_track_length):
        track.classification = "short_lived"
        track.reject_reason = "short_lived_track"
        return
    if max_delay_std_ns is not None and track.delay_std_ns > float(max_delay_std_ns):
        track.classification = "unstable_candidate"
        track.reject_reason = "unstable_delay"
        return
    if max_doppler_std_hz is not None and track.doppler_std_hz > float(max_doppler_std_hz):
        track.classification = "unstable_candidate"
        track.reject_reason = "unstable_doppler"
        return
    track.classification = "validated_mpc"
    track.reject_reason = ""


def link_sage_candidates(
    candidates: list[SageCandidate],
    *,
    delay_gate_ns: float = 100.0,
    doppler_gate_hz: float = 25.0,
    max_gap_windows: int = 1,
    min_track_length: int = 3,
    max_delay_std_ns: float | None = None,
    max_doppler_std_hz: float | None = None,
) -> SageValidationResult:
    """Greedy delay-Doppler track association for SAGE candidates.

    This is intentionally lightweight: it turns single-window SAGE candidates
    into track hypotheses and annotates stable tracks as validated MPCs.  It is
    not a final JPDA/PMBM tracker, but it creates the explicit raw -> track ->
    validated/rejected separation needed by the SAGE pipeline.
    """
    if delay_gate_ns <= 0 or doppler_gate_hz <= 0:
        raise ValueError("delay_gate_ns and doppler_gate_hz must be positive")
    ordered = sorted(candidates, key=lambda c: (c.window_index, -c.power_db, c.delay_ns))
    by_window: dict[int, list[SageCandidate]] = {}
    for cand in ordered:
        by_window.setdefault(cand.window_index, []).append(cand)

    tracks: list[SageTrack] = []
    active: list[SageTrack] = []
    next_id = 1
    for window in sorted(by_window):
        current = by_window[window]
        viable_active = [
            tr for tr in active
            if window - tr.candidates[-1].window_index <= max_gap_windows + 1
        ]
        possible: list[tuple[float, int, int]] = []
        for ti, track in enumerate(viable_active):
            previous = track.candidates[-1]
            for ci, cand in enumerate(current):
                dist = _candidate_distance(
                    previous,
                    cand,
                    delay_gate_ns=delay_gate_ns,
                    doppler_gate_hz=doppler_gate_hz,
                )
                if dist is not None:
                    possible.append((dist, ti, ci))
        used_tracks: set[int] = set()
        used_candidates: set[int] = set()
        for _, ti, ci in sorted(possible, key=lambda x: x[0]):
            if ti in used_tracks or ci in used_candidates:
                continue
            viable_active[ti].candidates.append(current[ci])
            used_tracks.add(ti)
            used_candidates.add(ci)
        new_tracks = []
        for ci, cand in enumerate(current):
            if ci in used_candidates:
                continue
            track = SageTrack(track_id=next_id, candidates=[cand])
            next_id += 1
            tracks.append(track)
            new_tracks.append(track)
        active = [
            tr for tr in tracks
            if window - tr.candidates[-1].window_index <= max_gap_windows
        ] + new_tracks
        # De-duplicate active list while preserving order.
        seen: set[int] = set()
        unique_active: list[SageTrack] = []
        for tr in active:
            if tr.track_id not in seen:
                unique_active.append(tr)
                seen.add(tr.track_id)
        active = unique_active

    for track in tracks:
        _classify_track(
            track,
            min_track_length=min_track_length,
            max_delay_std_ns=max_delay_std_ns,
            max_doppler_std_hz=max_doppler_std_hz,
        )
    return SageValidationResult(tracks=tracks)


def classify_candidates_by_tracks(
    candidates: list[SageCandidate],
    **kwargs,
) -> SageValidationResult:
    """Alias with a name that emphasizes validation/classification output."""
    return link_sage_candidates(candidates, **kwargs)
