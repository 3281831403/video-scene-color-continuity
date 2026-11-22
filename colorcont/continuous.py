"""Colour-continuity primitives for a scene that was cut into several shots.

Shapes used throughout::

    pixel  = [r, g, b]
    frame  = [[pixel, ...], ...]        # rows of pixels
    shot   = [frame, ...]
    scene  = [shot, ...]
    batch  = [scene, ...]

Every sample is a linear-light float in ``0.0 .. 1.0``; gamma encoding never
enters this module, so a correction that is linear in the numbers is linear in
light as well.  Colour temperatures are kelvin.  Tests compare floats with an
absolute tolerance of ``ATOL`` (``1e-9``) and gain products with
``GAIN_PRODUCT_TOL`` (``0.01``).
"""

import math

CLIP_LEVEL = 0.98
"""Highlights at or above this level are treated as clipped, unusable data."""

CLIP_CEILING = 1.0
"""Largest value a channel may carry; applied as an output ceiling."""

TEMP_MIN = 2000.0
"""Warm end of the accepted colour-temperature range, in kelvin."""

TEMP_MAX = 12000.0
"""Cool end of the accepted colour-temperature range, in kelvin."""

NEUTRAL_K = 6500.0
"""Colour temperature of a neutral red/blue balance, in kelvin."""

GAIN_PRODUCT_TOL = 0.01
"""How far a gain triple's product may drift from ``1.0`` before it is a bug."""

ATOL = 1e-9
"""Absolute tolerance used by the tests for every float comparison."""


def scene_stats(frames):
    """Measure one shot: channel means, colour temperature, size.

    ``frames`` is a shot (see the module docstring).  A pixel is *usable* only
    when all three of its channels are strictly below ``CLIP_LEVEL``; clipped
    highlights saturate to white and would otherwise drag the estimate towards
    whatever hue the sensor clipped first, so they are dropped from
    measurement.

    Returns a fresh dict with:

    ``"mean"``
        ``(r, g, b)`` arithmetic mean of the usable pixels, taken over every
        pixel of every frame.  ``(0.0, 0.0, 0.0)`` when no pixel is usable.
    ``"temp_k"``
        Correlated colour temperature of that mean: ``NEUTRAL_K * b / r``
        clamped to ``[TEMP_MIN, TEMP_MAX]``.  A mean with ``r <= 0`` but
        ``b > 0`` sits at the cool end; a mean with both zero carries no hue
        and reports ``NEUTRAL_K``.
    ``"duration"``
        Number of frames in the shot, i.e. ``len(frames)``.
    ``"pixels"``
        Number of pixels that were actually measured.
    """

    sum_r = sum_g = sum_b = 0.0
    count = 0
    for frame in frames:
        for row in frame:
            for pixel in row:
                r, g, b = pixel
                if r < CLIP_LEVEL and g < CLIP_LEVEL and b < CLIP_LEVEL:
                    sum_r += r
                    sum_g += g
                    sum_b += b
                    count += 1

    if count:
        mean = (sum_r / count, sum_g / count, sum_b / count)
    else:
        mean = (0.0, 0.0, 0.0)

    r, _, b = mean
    if r <= 0.0:
        temp_k = TEMP_MAX if b > 0.0 else NEUTRAL_K
    else:
        temp_k = min(TEMP_MAX, max(TEMP_MIN, NEUTRAL_K * b / r))

    return {
        "mean": mean,
        "temp_k": temp_k,
        "duration": len(frames),
        "pixels": count,
    }


def choose_reference(stats):
    """Pick the shot that the rest of the scene should be matched against.

    ``stats`` is a sequence of dicts as returned by :func:`scene_stats`.  A
    scene has one true colour balance, and the middle of the distribution is
    the least surprising guess at it: the reference is the shot whose
    ``"temp_k"`` equals the median temperature
    ``sorted(temps)[(len(temps) - 1) // 2]`` (for an even count that is the
    lower of the two middle values).

    Ties on temperature are broken by the longest ``"duration"``, so the shot
    that contributes most screen time wins; if that also ties, the smallest
    index wins.  An empty sequence has no reference and returns ``-1``.
    """

    if not stats:
        return -1

    temps = [entry["temp_k"] for entry in stats]
    median = sorted(temps)[(len(temps) - 1) // 2]

    best = -1
    for index, entry in enumerate(stats):
        if entry["temp_k"] != median:
            continue
        if best < 0 or entry["duration"] > stats[best]["duration"]:
            best = index
    return best


def balance_gains(src, ref):
    """Gains that move the shot mean ``src`` towards the reference mean ``ref``.

    ``src`` and ``ref`` are ``(r, g, b)`` means in linear light.  Green is the
    anchor channel: it carries most of the luminance, so only the red/green and
    blue/green ratios are corrected, never green's own level::

        kr = (ref_r / ref_g) / (src_r / src_g)
        kb = (ref_b / ref_g) / (src_b / src_g)

    The triple ``(kr, 1.0, kb)`` is then divided by its own geometric mean, so
    the returned gains satisfy ``gain_r * gain_g * gain_b == 1.0`` and the
    shot's exposure is conserved instead of drifting with the colour cast.
    This is the von Kries diagonal solution with a green anchor, renormalised
    to unit product.

    Returns ``(gain_r, gain_g, gain_b)``.  A non-positive channel in ``src`` or
    ``ref`` makes the ratio meaningless and raises ``ValueError``.
    """

    src_r, src_g, src_b = src
    ref_r, ref_g, ref_b = ref
    if min(src_r, src_g, src_b, ref_r, ref_g, ref_b) <= 0.0:
        raise ValueError("channel means must be positive to balance")

    kr = (ref_r / ref_g) / (src_r / src_g)
    kb = (ref_b / ref_g) / (src_b / src_g)
    scale = (kr * kb) ** (1.0 / 3.0)
    return (kr / scale, 1.0 / scale, kb / scale)


def apply_gains(frames, gains):
    """Multiply a shot by ``gains`` and clamp the result.

    ``gains`` is ``(gain_r, gain_g, gain_b)``.  The multiplication happens on
    the linear values, so the result matches the same correction expressed in
    light, and every output channel is clamped to ``[0.0, CLIP_CEILING]``.

    Pixels that are already clipped - any channel at or above
    ``CLIP_CEILING`` - are copied through untouched.  They hold no recoverable
    detail, and scaling them would open a visible step against their
    neighbours right at the overexposed edge.

    ``frames`` is not modified; a new nested list of the same shape is
    returned.
    """

    gain_r, gain_g, gain_b = gains

    def correct(pixel):
        r, g, b = pixel
        if r >= CLIP_CEILING or g >= CLIP_CEILING or b >= CLIP_CEILING:
            return [r, g, b]
        return [
            min(CLIP_CEILING, max(0.0, r * gain_r)),
            min(CLIP_CEILING, max(0.0, g * gain_g)),
            min(CLIP_CEILING, max(0.0, b * gain_b)),
        ]

    return [[[correct(pixel) for pixel in row] for row in frame] for frame in frames]


def continuity_score(stats):
    """How far apart the shots sit in colour, as a number in ``0.0 .. 1.0``.

    Each shot's mean is reduced to chromaticity by dividing it by its channel
    sum, which makes the measure blind to exposure: a shot and a brighter copy
    of the same shot score ``0.0``.  A black mean has no chromaticity and is
    treated as ``(1/3, 1/3, 1/3)``.

    The score is the largest pairwise distance between those chromaticity
    vectors, each distance being half the L1 (city-block) distance between the
    two vectors.  That is ``0.0`` for identical colour and ``1.0`` for the two
    most opposed corners of the chromaticity triangle, so the score is already
    normalised and never scales with brightness.  Fewer than two shots score
    ``0.0``.
    """

    if len(stats) < 2:
        return 0.0

    chromas = []
    for entry in stats:
        r, g, b = entry["mean"]
        total = r + g + b
        if total > 0.0:
            chromas.append((r / total, g / total, b / total))
        else:
            chromas.append((1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0))

    worst = 0.0
    for i in range(len(chromas)):
        for j in range(i + 1, len(chromas)):
            distance = 0.5 * sum(
                abs(a - b) for a, b in zip(chromas[i], chromas[j])
            )
            if distance > worst:
                worst = distance
    return worst


def smooth_transition(a, b, t):
    """Blend two ``(r, g, b)`` colours across a shot boundary.

    ``t`` is clamped to ``[0.0, 1.0]``; values outside that range never
    extrapolate past the colours that actually exist on either side of the
    cut.  ``t <= 0.0`` returns ``a`` and ``t >= 1.0`` returns ``b`` verbatim,
    so a boundary frame is bit-identical to the shot it belongs to.  Anything
    in between interpolates linearly, channel by channel.  Returns a 3-tuple.
    """

    if t <= 0.0:
        return (a[0], a[1], a[2])
    if t >= 1.0:
        return (b[0], b[1], b[2])
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def _finite_triple(value):
    """Return the value as a float triple, or ``None`` when malformed."""

    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        triple = tuple(float(channel) for channel in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(channel) for channel in triple):
        return None
    return triple


def validate(stats, gains, *, temp_min=TEMP_MIN, temp_max=TEMP_MAX,
             gain_tolerance=GAIN_PRODUCT_TOL):
    """Report everything wrong with a candidate balance for one scene.

    ``stats`` is a sequence of :func:`scene_stats` dicts and ``gains`` the
    matching sequence of ``(r, g, b)`` gain triples, one per shot.  Nothing
    raises here: every problem becomes a short human-readable string and the
    caller decides what to do with the list.  An empty list means the scene is
    clean.

    Reported problems, in order of detection:

    * the two sequences differ in length;
    * a mean is malformed, missing, or not finite - the message contains
      ``nan``;
    * a mean's channel sum is not positive, so the shot has no usable pixels;
    * ``"temp_k"`` is not finite, or falls outside ``[temp_min, temp_max]`` -
      the message contains ``temperature``;
    * a gain triple is malformed or not finite - the message contains ``nan``;
    * a gain triple's product misses ``1.0`` by more than ``gain_tolerance``,
      meaning the correction would clip or dim the whole shot - the message
      contains ``product``.

    ``temp_min``, ``temp_max`` and ``gain_tolerance`` are keyword-only
    overrides of the module defaults.
    """

    problems = []

    if len(stats) != len(gains):
        problems.append(
            "shot count mismatch: %d stats vs %d gain triples"
            % (len(stats), len(gains))
        )

    for index, (entry, triple) in enumerate(zip(stats, gains)):
        mean = _finite_triple(entry.get("mean") if isinstance(entry, dict) else None)
        if mean is None:
            problems.append("shot %d: mean is missing, malformed, or nan" % index)
        else:
            if sum(mean) <= 0.0:
                problems.append(
                    "shot %d: mean channel sum is not positive" % index
                )
            temp_k = entry.get("temp_k")
            if (
                not isinstance(temp_k, (int, float))
                or not math.isfinite(temp_k)
                or temp_k < temp_min
                or temp_k > temp_max
            ):
                problems.append(
                    "shot %d: temperature %r outside [%g, %g]"
                    % (index, temp_k, temp_min, temp_max)
                )

        gain = _finite_triple(triple)
        if gain is None:
            problems.append("shot %d: gain triple is malformed or nan" % index)
        elif abs(gain[0] * gain[1] * gain[2] - 1.0) > gain_tolerance:
            problems.append(
                "shot %d: gain product %g drifts from 1.0"
                % (index, gain[0] * gain[1] * gain[2])
            )

    return problems


def continuity_batch(scenes, config):
    """Balance a whole batch of scenes, keeping the scenes apart.

    ``scenes`` is a list of scenes; a scene is a list of shots, and a shot is a
    list of frames as described in the module docstring.  Every scene picks its
    own reference shot from its own statistics, so a run of scenes behaves
    exactly like the same scenes processed one at a time - nothing is carried
    from one scene to the next.

    ``config`` is a dict of overrides.  Recognised keys are ``"temp_min"``,
    ``"temp_max"``, ``"gain_tolerance"`` (forwarded to :func:`validate`) and
    ``"score_threshold"``: a scene whose :func:`continuity_score` exceeds it
    gains a problem entry.  Missing keys fall back to the module defaults and
    unknown keys are ignored.

    Returns a dict of per-scene lists, index-aligned with ``scenes``:

    ``"references"``
        ``choose_reference`` result for the scene.
    ``"stats"``
        List of :func:`scene_stats` dicts, one per shot.
    ``"gains"``
        List of gain triples, one per shot.
    ``"shots"``
        The balanced shots, in input order.
    ``"scores"``
        The scene's :func:`continuity_score` after balancing.
    ``"problems"``
        One list of validation strings per scene.
    ``"ok"``
        ``True`` only when every per-scene problem list is empty.

    A shot whose mean has a non-positive channel cannot be balanced: it keeps
    identity gains and adds a problem instead of raising.  An empty scene
    reports reference ``-1``, empty lists, score ``0.0``, and a problem
    string.
    """

    config = config or {}
    temp_min = config.get("temp_min", TEMP_MIN)
    temp_max = config.get("temp_max", TEMP_MAX)
    gain_tolerance = config.get("gain_tolerance", GAIN_PRODUCT_TOL)
    score_threshold = config.get("score_threshold")

    references = []
    all_stats = []
    all_gains = []
    all_shots = []
    scores = []
    all_problems = []

    for scene in scenes:
        if not scene:
            references.append(-1)
            all_stats.append([])
            all_gains.append([])
            all_shots.append([])
            scores.append(0.0)
            all_problems.append(["scene has no shots"])
            continue

        stats = [scene_stats(shot) for shot in scene]
        reference = choose_reference(stats)
        ref_mean = stats[reference]["mean"]

        gains = []
        problems = []
        for index, entry in enumerate(stats):
            try:
                gains.append(balance_gains(entry["mean"], ref_mean))
            except ValueError:
                gains.append((1.0, 1.0, 1.0))
                problems.append(
                    "shot %d: mean has a non-positive channel, "
                    "left unbalanced" % index
                )

        balanced = [apply_gains(shot, triple) for shot, triple in zip(scene, gains)]
        balanced_stats = [scene_stats(shot) for shot in balanced]
        score = continuity_score(balanced_stats)

        problems.extend(
            validate(
                stats,
                gains,
                temp_min=temp_min,
                temp_max=temp_max,
                gain_tolerance=gain_tolerance,
            )
        )
        if score_threshold is not None and score > score_threshold:
            problems.append(
                "continuity score %g exceeds threshold %g"
                % (score, score_threshold)
            )

        references.append(reference)
        all_stats.append(stats)
        all_gains.append(gains)
        all_shots.append(balanced)
        scores.append(score)
        all_problems.append(problems)

    return {
        "references": references,
        "stats": all_stats,
        "gains": all_gains,
        "shots": all_shots,
        "scores": scores,
        "problems": all_problems,
        "ok": all(not problems for problems in all_problems),
    }
