"""Executable specification for the colour-continuity stubs.

Exactly 15 tests: ten that pin down the ten documented defects and five that
guard the wider contract.  Every test calls at least one public stub from
``colorcont.continuous``, and every float comparison is absolute at ``ATOL``
(``1e-9``) unless the test says otherwise.
"""

import math

import pytest

from colorcont.continuous import (
    ATOL,
    CLIP_CEILING,
    CLIP_LEVEL,
    NEUTRAL_K,
    apply_gains,
    balance_gains,
    choose_reference,
    continuity_batch,
    continuity_score,
    scene_stats,
    smooth_transition,
    validate,
)


def shot(pixels, frames=1):
    """A shot of ``frames`` identical frames, each a single row of ``pixels``."""
    return [[[list(pixel) for pixel in pixels]] for _ in range(frames)]


def _flatten(value):
    """Depth-first float list of a nested pixel or gain structure."""
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(_flatten(item))
        return out
    return [float(value)]


def test_scene_stats_drops_clipped_highlights():
    """Defect 1: a clipped highlight must not pull the colour estimate."""
    base = (0.30, 0.25, 0.20)
    clipped = (0.10, CLIP_LEVEL + 0.01, 1.00)
    lens = shot([base] * 9 + [clipped])

    stats = scene_stats(lens)

    assert stats["mean"] == pytest.approx(base, abs=ATOL)
    assert stats["pixels"] == 9
    assert stats["duration"] == 1
    assert stats["temp_k"] == pytest.approx(NEUTRAL_K * 0.20 / 0.30, abs=ATOL)

    blown = scene_stats(shot([(1.0, 1.0, 1.0)]))

    assert blown["mean"] == (0.0, 0.0, 0.0)
    assert blown["pixels"] == 0
    assert blown["temp_k"] == NEUTRAL_K


def test_choose_reference_follows_median_temperature():
    """Defect 2: the reference is the median-temperature shot, not shot zero."""
    cool = shot([(0.20, 0.40, 0.30)])
    neutral = shot([(0.30, 0.30, 0.30)])
    warm = shot([(0.40, 0.30, 0.30)])

    stats = [scene_stats(lens) for lens in (cool, neutral, warm)]

    assert choose_reference(stats) == 1
    assert choose_reference([]) == -1

    short_take = shot([(0.30, 0.30, 0.30)])
    long_take = shot([(0.30, 0.30, 0.30)], frames=3)
    tied = [scene_stats(lens) for lens in (cool, short_take, long_take, warm)]

    assert choose_reference(tied) == 2


def test_balance_gains_keeps_exposure_neutral():
    """Defect 3: scaling green too would drift the whole shot's brightness."""
    src = (0.20, 0.45, 0.20)
    ref = (0.30, 0.30, 0.30)

    kr = (ref[0] / ref[1]) / (src[0] / src[1])
    kb = (ref[2] / ref[1]) / (src[2] / src[1])
    scale = (kr * kb) ** (1.0 / 3.0)

    gains = balance_gains(src, ref)

    assert gains == pytest.approx((kr / scale, 1.0 / scale, kb / scale), abs=ATOL)
    assert gains[0] * gains[1] * gains[2] == pytest.approx(1.0, abs=ATOL)
    assert gains[1] < 1.0


def test_balance_gains_never_swaps_red_and_blue():
    """Defect 4: warm light must lose red and gain blue, not the other way."""
    src = (0.40, 0.30, 0.20)
    ref = (0.30, 0.30, 0.30)

    kr = (ref[0] / ref[1]) / (src[0] / src[1])
    kb = (ref[2] / ref[1]) / (src[2] / src[1])
    scale = (kr * kb) ** (1.0 / 3.0)

    gains = balance_gains(src, ref)

    assert gains[0] == pytest.approx(kr / scale, abs=ATOL)
    assert gains[2] == pytest.approx(kb / scale, abs=ATOL)
    assert gains[0] < 1.0 < gains[2]


def test_apply_gains_works_on_linear_light():
    """Defect 5: gains multiply linear values, not gamma-encoded ones."""
    scene = shot([(0.25, 0.25, 0.25), (0.0625, 0.0625, 0.0625)])

    row = apply_gains(scene, (1.5, 1.5, 1.5))[0][0]

    assert row[0] == pytest.approx([0.375, 0.375, 0.375], abs=ATOL)
    assert row[1] == pytest.approx([0.09375, 0.09375, 0.09375], abs=ATOL)
    assert scene[0][0][0] == [0.25, 0.25, 0.25]


def test_continuity_score_ignores_exposure():
    """Defect 6: the score normalises chroma, so brightness cannot move it."""
    dim = scene_stats(shot([(0.10, 0.20, 0.30)]))
    bright = scene_stats(shot([(0.20, 0.40, 0.60)]))

    assert continuity_score([dim, bright]) == pytest.approx(0.0, abs=ATOL)
    assert continuity_score([]) == 0.0

    red = scene_stats(shot([(0.90, 0.05, 0.05)]))
    blue = scene_stats(shot([(0.05, 0.05, 0.90)]))
    score = continuity_score([red, blue])

    assert score == pytest.approx(0.85, abs=ATOL)
    assert 0.0 <= score <= 1.0


def test_smooth_transition_clamps_parameter():
    """Defect 7: t outside [0, 1] must not extrapolate past the boundary."""
    a = (0.10, 0.20, 0.30)
    b = (0.70, 0.60, 0.50)

    assert smooth_transition(a, b, -0.5) == pytest.approx(a, abs=ATOL)
    assert smooth_transition(a, b, 1.5) == pytest.approx(b, abs=ATOL)
    assert smooth_transition(a, b, 4.0) == pytest.approx(b, abs=ATOL)
    assert smooth_transition(a, b, 0.5) == pytest.approx((0.40, 0.40, 0.40), abs=ATOL)


def test_validate_flags_gain_product():
    """Defect 8: gains that double the exposure must be reported."""
    stats = [scene_stats(shot([(0.30, 0.30, 0.30)])) for _ in range(3)]

    problems = validate(stats, [(1.0, 1.0, 1.0), (2.0, 1.0, 1.0), (1.0, 1.0, 1.0)])

    assert any("product" in problem.lower() for problem in problems)
    assert validate(stats, [(1.0, 1.0, 1.0)] * 3) == []

    hot = [{"mean": (0.30, 0.30, 0.30), "temp_k": 900.0, "duration": 1, "pixels": 1}]
    broken = [
        {
            "mean": (float("nan"), 0.30, 0.30),
            "temp_k": NEUTRAL_K,
            "duration": 1,
            "pixels": 1,
        }
    ]

    assert any("temperature" in problem.lower() for problem in validate(hot, [(1.0, 1.0, 1.0)]))
    assert any("nan" in problem.lower() for problem in validate(broken, [(1.0, 1.0, 1.0)]))


def test_continuity_batch_references_each_scene_separately():
    """Defect 9: scene two must not inherit scene one's reference shot."""
    scene_a = [
        shot([(0.20, 0.40, 0.30)]),
        shot([(0.30, 0.30, 0.30)]),
        shot([(0.40, 0.30, 0.30)]),
    ]
    scene_b = [
        shot([(0.40, 0.30, 0.30)]),
        shot([(0.20, 0.40, 0.30)]),
        shot([(0.30, 0.30, 0.30)]),
    ]

    result = continuity_batch([scene_a, scene_b], {})

    assert result["references"] == [1, 2]
    assert result["gains"][0][1] == pytest.approx((1.0, 1.0, 1.0), abs=ATOL)
    assert result["gains"][1][2] == pytest.approx((1.0, 1.0, 1.0), abs=ATOL)


def test_apply_gains_leaves_clipped_pixels_alone():
    """Defect 10: a clipped pixel must not be darkened into a hard edge."""
    scene = shot(
        [(CLIP_CEILING, CLIP_CEILING, CLIP_CEILING), (0.50, 0.50, 0.50), (0.25, 0.25, 0.25)]
    )

    row = apply_gains(scene, (0.8, 0.8, 0.8))[0][0]

    assert row[0] == pytest.approx([1.0, 1.0, 1.0], abs=ATOL)
    assert row[1] == pytest.approx([0.40, 0.40, 0.40], abs=ATOL)
    assert row[2] == pytest.approx([0.20, 0.20, 0.20], abs=ATOL)
    assert row[0][0] > row[1][0]


def test_three_identical_shots_come_back_unchanged():
    """Extra: identical shots need no correction and must not move at 1e-9."""

    def take():
        return [[[[0.42, 0.38, 0.36], [0.20, 0.18, 0.16]]]]

    scene = [take(), take(), take()]

    result = continuity_batch([scene], {})

    assert result["references"] == [0]
    for original, balanced in zip(scene, result["shots"][0]):
        assert _flatten(balanced) == pytest.approx(_flatten(original), abs=ATOL)
    for gains in result["gains"][0]:
        assert gains == pytest.approx((1.0, 1.0, 1.0), abs=ATOL)
    assert result["ok"]


def test_green_cast_shot_loses_green():
    """Extra: balancing a green shot must lower its green mean."""
    green = shot([(0.20, 0.45, 0.20), (0.22, 0.47, 0.18)])
    before = scene_stats(green)["mean"]

    gains = balance_gains(before, (0.30, 0.30, 0.30))
    after = scene_stats(apply_gains(green, gains))["mean"]

    assert after[1] < before[1]
    assert after[0] == pytest.approx(after[1], abs=ATOL)
    assert after[2] == pytest.approx(after[1], abs=ATOL)


def test_transition_endpoints_reproduce_inputs():
    """Extra: t=0 is exactly a and t=1 is exactly b, at 1e-9."""
    a = (0.12, 0.34, 0.56)
    b = (0.78, 0.66, 0.44)

    assert smooth_transition(a, b, 0.0) == pytest.approx(a, abs=ATOL)
    assert smooth_transition(a, b, 1.0) == pytest.approx(b, abs=ATOL)


def test_batch_gains_multiply_to_one():
    """Extra: every gain triple is exposure neutral to within 1e-2."""
    scene = [
        shot([(0.20, 0.40, 0.30)]),
        shot([(0.30, 0.30, 0.30)]),
        shot([(0.40, 0.30, 0.30)]),
    ]

    result = continuity_batch([scene], {})

    for gains in result["gains"][0]:
        assert math.prod(gains) == pytest.approx(1.0, abs=0.01)
    assert result["gains"][0][1] == pytest.approx((1.0, 1.0, 1.0), abs=ATOL)


def test_scenes_in_a_batch_match_solo_runs():
    """Extra: batching two scenes equals running each scene on its own."""
    scene_a = [
        shot([(0.20, 0.40, 0.30)]),
        shot([(0.30, 0.30, 0.30)]),
        shot([(0.40, 0.30, 0.30)]),
    ]
    scene_b = [
        shot([(0.40, 0.30, 0.30)]),
        shot([(0.20, 0.40, 0.30)]),
        shot([(0.30, 0.30, 0.30)]),
    ]

    batch = continuity_batch([scene_a, scene_b], {})
    solo_a = continuity_batch([scene_a], {})
    solo_b = continuity_batch([scene_b], {})

    assert batch["references"] == [solo_a["references"][0], solo_b["references"][0]]
    for index, solo in enumerate((solo_a, solo_b)):
        assert _flatten(batch["gains"][index]) == pytest.approx(
            _flatten(solo["gains"][0]), abs=ATOL
        )
        assert _flatten(batch["shots"][index]) == pytest.approx(
            _flatten(solo["shots"][0]), abs=ATOL
        )
        assert batch["scores"][index] == pytest.approx(solo["scores"][0], abs=ATOL)
