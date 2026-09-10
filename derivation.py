"""Pure derivation logic for the IA Mapping tool.

No Streamlit, no network, no file IO — just functions that turn a task's
inputs into bands, a quadrant, a sequence position, and a suggested redesign
action. This is the part reviewers should be able to read and check in
isolation, and it is the only part with full unit-test coverage.

Pipeline for one task:

    round-1 score (1-10)  --cut points-->  band (1-4)
    human band override   ----------------> band (1-4)   [wins unless re-scoring]
    two bands             --high/low-------> quadrant
    two bands             --weaker axis----> action tier (axis-only)
    action tier + position -----------------> action tier (position-aware)

`derive_task` ties it together and returns a `Derivation`.
"""

from __future__ import annotations

from dataclasses import dataclass

import config

# --------------------------------------------------------------------------
# Small pure helpers
# --------------------------------------------------------------------------


def band_from_score(score: float, cut_points: tuple[int, int, int] | None = None) -> int:
    """Band a round-1 numeric score (1-10) to a 1-4 ordinal.

    >= high -> 4, >= mid -> 3, >= low -> 2, else 1.
    """
    low, mid, high = cut_points or config.DEFAULT_CUT_POINTS
    if not low <= mid <= high:
        raise ValueError(f"cut points must be non-decreasing, got {(low, mid, high)}")
    if score >= high:
        return 4
    if score >= mid:
        return 3
    if score >= low:
        return 2
    return 1


def assure_label(band: int) -> str:
    """1-4 ordinal -> Assure band label."""
    return config.ASSURE_BANDS[_check_ordinal(band) - 1]


def inspire_label(band: int) -> str:
    """1-4 ordinal -> Inspire band label."""
    return config.INSPIRE_BANDS[_check_ordinal(band) - 1]


def assure_ordinal(label: str) -> int:
    """Assure band label -> 1-4 ordinal."""
    return config.ASSURE_BANDS.index(label) + 1


def inspire_ordinal(label: str) -> int:
    """Inspire band label -> 1-4 ordinal."""
    return config.INSPIRE_BANDS.index(label) + 1


def is_high(band: int) -> bool:
    """Collapse a 1-4 band to the high/low used for the quadrant."""
    return _check_ordinal(band) >= config.HIGH_BAND_THRESHOLD


def quadrant(inspire_band: int, assure_band: int) -> str:
    """Cross the two high/low rollups into one of the four quadrant names."""
    inspire_high = is_high(inspire_band)
    assure_high = is_high(assure_band)
    if inspire_high and assure_high:
        return "High Inspire · High Assure"
    if inspire_high and not assure_high:
        return "High Inspire · Low Assure"
    if not inspire_high and assure_high:
        return "Low Inspire · High Assure"
    return "Low Inspire · Low Assure"


def position(assessment_number: int | None, subject_max_number: int | None) -> str:
    """Where the task sits in the subject's assessment sequence.

    number == 1 and max >= 2       -> "early"
    number == max and max >= 2     -> "final"
    number present, 1 < number < max -> "mid"
    number missing, or max < 2     -> "single"
    """
    if assessment_number is None or subject_max_number is None or subject_max_number < 2:
        return "single"
    if assessment_number == 1:
        return "early"
    if assessment_number == subject_max_number:
        return "final"
    return "mid"


def action_tier(weaker_band: int) -> str:
    """Weaker of the two axis bands -> redesign action tier."""
    return config.ACTIONS[4 - _check_ordinal(weaker_band)]


# --------------------------------------------------------------------------
# Position weighting
# --------------------------------------------------------------------------


def apply_position_weighting(
    assure_band: int,
    inspire_band: int,
    pos: str,
) -> tuple[str, str | None]:
    """Return (position-aware action tier, reason or None).

    Softens ONLY the axis that isn't the point of that stage, and only when
    that axis is the weaker one and sits at Potential/Not:

      * early  + weak assure  -> treat assure as one band stronger
      * final  + weak inspire -> treat inspire as one band stronger

    Inspiration is never softened at an early task; assurance is never
    softened at a final task; "mid" and "single" are never softened.
    """
    assure_eff, inspire_eff = assure_band, inspire_band
    reason: str | None = None

    if pos == "early" and assure_band < inspire_band and assure_band <= 2:
        assure_eff = min(4, assure_band + 1)
        reason = config.REASON_EARLY_SOFTEN_ASSURE
    elif pos == "final" and inspire_band < assure_band and inspire_band <= 2:
        inspire_eff = min(4, inspire_band + 1)
        reason = config.REASON_FINAL_SOFTEN_INSPIRE

    return action_tier(min(assure_eff, inspire_eff)), reason


# --------------------------------------------------------------------------
# Band resolution (the seeding rule)
# --------------------------------------------------------------------------

BandSource = str  # "human" | "round1" | "manual"


def resolve_band(
    override_label: str | None,
    score: float | None,
    labels: list[str],
    *,
    confirmed: bool,
    rescore: bool,
    cut_points: tuple[int, int, int] | None,
) -> tuple[int | None, BandSource]:
    """Decide the working band for one axis.

    Priority:
      1. a confirmed row keeps its stored human band, always;
      2. otherwise, if the reviewer asked to re-score, the round-1 score wins;
      3. otherwise an existing human band wins;
      4. otherwise the round-1 score is banded;
      5. otherwise there is nothing to go on -> (None, "manual").
    """
    has_override = override_label in labels
    override_ord = labels.index(override_label) + 1 if has_override else None

    if confirmed and has_override:
        return override_ord, "human"
    if rescore and score is not None:
        return band_from_score(score, cut_points), "round1"
    if has_override:
        return override_ord, "human"
    if score is not None:
        return band_from_score(score, cut_points), "round1"
    return None, "manual"


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Derivation:
    """Everything derived for one task. Band fields are None when the task
    still needs a band set by hand (`needs_manual` is then True)."""

    assure_band: str | None
    inspire_band: str | None
    assure_band_n: int | None
    inspire_band_n: int | None
    assure_source: BandSource
    inspire_source: BandSource
    assure_high: bool | None
    inspire_high: bool | None
    quadrant: str | None
    position: str
    action_axis_only: str | None
    action_suggested: str | None
    position_changed_action: bool
    action_reason: str | None
    needs_manual: bool


def derive_task(
    *,
    assure_score: float | None = None,
    inspire_score: float | None = None,
    assure_band_override: str | None = None,
    inspire_band_override: str | None = None,
    assessment_number: int | None = None,
    subject_max_number: int | None = None,
    confirmed: bool = False,
    rescore: bool = False,
    weight_by_position: bool = config.WEIGHT_BY_POSITION_DEFAULT,
    cut_points: tuple[int, int, int] | None = None,
) -> Derivation:
    """Derive bands, quadrant, position and suggested action for one task."""
    assure_n, assure_src = resolve_band(
        assure_band_override, assure_score, config.ASSURE_BANDS,
        confirmed=confirmed, rescore=rescore, cut_points=cut_points,
    )
    inspire_n, inspire_src = resolve_band(
        inspire_band_override, inspire_score, config.INSPIRE_BANDS,
        confirmed=confirmed, rescore=rescore, cut_points=cut_points,
    )

    pos = position(assessment_number, subject_max_number)

    if assure_n is None or inspire_n is None:
        return Derivation(
            assure_band=assure_label(assure_n) if assure_n else None,
            inspire_band=inspire_label(inspire_n) if inspire_n else None,
            assure_band_n=assure_n,
            inspire_band_n=inspire_n,
            assure_source=assure_src,
            inspire_source=inspire_src,
            assure_high=is_high(assure_n) if assure_n else None,
            inspire_high=is_high(inspire_n) if inspire_n else None,
            quadrant=None,
            position=pos,
            action_axis_only=None,
            action_suggested=None,
            position_changed_action=False,
            action_reason=None,
            needs_manual=True,
        )

    axis_only = action_tier(min(assure_n, inspire_n))

    if weight_by_position:
        suggested, reason = apply_position_weighting(assure_n, inspire_n, pos)
    else:
        suggested, reason = axis_only, None

    return Derivation(
        assure_band=assure_label(assure_n),
        inspire_band=inspire_label(inspire_n),
        assure_band_n=assure_n,
        inspire_band_n=inspire_n,
        assure_source=assure_src,
        inspire_source=inspire_src,
        assure_high=is_high(assure_n),
        inspire_high=is_high(inspire_n),
        quadrant=quadrant(inspire_n, assure_n),
        position=pos,
        action_axis_only=axis_only,
        action_suggested=suggested,
        position_changed_action=(suggested != axis_only),
        action_reason=reason,
        needs_manual=False,
    )


# --------------------------------------------------------------------------
# internal
# --------------------------------------------------------------------------


def _check_ordinal(band: int) -> int:
    if band not in (1, 2, 3, 4):
        raise ValueError(f"band ordinal must be 1-4, got {band!r}")
    return band
