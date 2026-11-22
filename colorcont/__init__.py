"""Colour continuity helpers for multi-shot scene balancing."""

from .continuous import (
    ATOL,
    CLIP_CEILING,
    CLIP_LEVEL,
    GAIN_PRODUCT_TOL,
    NEUTRAL_K,
    TEMP_MAX,
    TEMP_MIN,
    apply_gains,
    balance_gains,
    choose_reference,
    continuity_batch,
    continuity_score,
    scene_stats,
    smooth_transition,
    validate,
)

__all__ = [
    "ATOL",
    "CLIP_CEILING",
    "CLIP_LEVEL",
    "GAIN_PRODUCT_TOL",
    "NEUTRAL_K",
    "TEMP_MAX",
    "TEMP_MIN",
    "apply_gains",
    "balance_gains",
    "choose_reference",
    "continuity_batch",
    "continuity_score",
    "scene_stats",
    "smooth_transition",
    "validate",
]
