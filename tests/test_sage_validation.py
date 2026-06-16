from __future__ import annotations

from src.signal.sage_validation import (
    SageCandidate,
    classify_candidates_by_tracks,
    link_sage_candidates,
)


def _cand(window: int, delay: float, doppler: float = 0.0, power: float = 0.0) -> SageCandidate:
    return SageCandidate(
        file="synthetic.bin",
        window_index=window,
        time_sec=0.5 * window,
        candidate_id=window + 1,
        delay_ns=delay,
        doppler_hz=doppler,
        power_db=power,
        score_db=power,
        source_kind="final",
    )


def test_link_sage_candidates_keeps_two_parallel_tracks_separate():
    candidates = []
    for w in range(5):
        candidates.append(_cand(w, 100.0 + w * 5.0, doppler=1.0, power=0.0))
        candidates.append(_cand(w, 500.0 + w * 4.0, doppler=-3.0, power=-8.0))

    result = link_sage_candidates(
        candidates,
        delay_gate_ns=60.0,
        doppler_gate_hz=5.0,
        max_gap_windows=0,
        min_track_length=3,
    )

    assert len(result.tracks) == 2
    assert len(result.validated_tracks) == 2
    medians = sorted(round(t.delay_median_ns) for t in result.validated_tracks)
    assert medians == [110, 508]
    assert all(t.classification == "validated_mpc" for t in result.validated_tracks)


def test_classify_candidates_marks_short_lived_candidate_with_reason():
    candidates = [_cand(w, 100.0, doppler=0.0, power=0.0) for w in range(5)]
    candidates.append(_cand(2, 900.0, doppler=40.0, power=-20.0))

    result = classify_candidates_by_tracks(
        candidates,
        delay_gate_ns=80.0,
        doppler_gate_hz=10.0,
        max_gap_windows=0,
        min_track_length=3,
    )

    short = [t for t in result.tracks if t.classification == "short_lived"]
    assert len(short) == 1
    assert short[0].reject_reason == "short_lived_track"
    assert short[0].length_windows == 1
    assert len(result.validated_tracks) == 1


def test_link_sage_candidates_allows_one_missing_window_gap():
    candidates = [
        _cand(0, 200.0, 5.0),
        _cand(1, 210.0, 5.5),
        _cand(3, 230.0, 5.0),
        _cand(4, 240.0, 4.8),
    ]

    result = link_sage_candidates(
        candidates,
        delay_gate_ns=50.0,
        doppler_gate_hz=3.0,
        max_gap_windows=1,
        min_track_length=3,
    )

    assert len(result.validated_tracks) == 1
    track = result.validated_tracks[0]
    assert track.length_windows == 4
    assert track.start_window == 0
    assert track.end_window == 4


def test_classify_candidates_marks_high_doppler_spread_as_unstable():
    candidates = [
        _cand(0, 300.0, 0.0),
        _cand(1, 305.0, 30.0),
        _cand(2, 310.0, -30.0),
        _cand(3, 315.0, 35.0),
    ]

    result = classify_candidates_by_tracks(
        candidates,
        delay_gate_ns=80.0,
        doppler_gate_hz=80.0,
        max_gap_windows=0,
        min_track_length=3,
        max_doppler_std_hz=20.0,
    )

    assert len(result.validated_tracks) == 0
    assert result.tracks[0].classification == "unstable_candidate"
    assert result.tracks[0].reject_reason == "unstable_doppler"
