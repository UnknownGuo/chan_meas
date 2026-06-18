"""Calibration constants tied to one specific measurement campaign.

These describe physical facts about how ``zjk_mea``'s B2B loopback
reference (``calibration/b2b_cir.npy``) was recorded — not generic
algorithm tuning knobs. Centralizing them here is the fix for a real bug:
the same numbers used to be duplicated as literals across five different
scripts, and a future change (e.g. re-recording B2B with a different
attenuator) would have required updating all five in lockstep.
"""

ZJK_B2B_ATTENUATION_DB: float = 60.0
"""Fixed attenuator inserted only while recording zjk_mea's B2B loopback
reference, to avoid saturating the receiver on a direct cable connection.
The real V2V/OTA measurement chain does not have this attenuator, so it
must be compensated when deconvolving with the B2B reference — see
``regularized_frequency_calibrate(attenuation_db=...)``."""

ZJK_B2B_REGULARIZATION: float = 1e-3
"""Tikhonov regularization (relative to max |H_b2b|^2) used when
deconvolving zjk_mea measurements with the B2B reference."""
