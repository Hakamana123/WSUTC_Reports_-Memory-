"""Unit tests for derivation.py — the rules reviewers need to trust.

Covered: every banding boundary, all four quadrants, every sequence position,
the two position-softening cases AND the cases that must NOT soften, and that
a confirmed row keeps its stored bands even when asked to re-score.
"""

from __future__ import annotations

import pytest

import config
import derivation as d


# --------------------------------------------------------------------------
# Banding a numeric round-1 score
# --------------------------------------------------------------------------


class TestBandFromScore:
    @pytest.mark.parametrize(
        "score, expected",
        [
            (1, 1), (2, 1), (3, 1),          # below low
            (3.99, 1),
            (4, 2), (5, 2), (5.99, 2),        # [low, mid)
            (6, 3), (7, 3), (7.99, 3),        # [mid, high)
            (8, 4), (9, 4), (10, 4),          # >= high
        ],
    )
    def test_default_cut_points(self, score, expected):
        assert d.band_from_score(score) == expected

    def test_boundaries_are_inclusive_lower(self):
        low, mid, high = config.DEFAULT_CUT_POINTS
        assert d.band_from_score(low) == 2
        assert d.band_from_score(mid) == 3
        assert d.band_from_score(high) == 4
        assert d.band_from_score(low - 0.01) == 1
        assert d.band_from_score(mid - 0.01) == 2
        assert d.band_from_score(high - 0.01) == 3

    def test_custom_cut_points(self):
        cuts = (3, 5, 7)
        assert d.band_from_score(3, cuts) == 2
        assert d.band_from_score(4, cuts) == 2
        assert d.band_from_score(5, cuts) == 3
        assert d.band_from_score(7, cuts) == 4

    def test_rejects_decreasing_cut_points(self):
        with pytest.raises(ValueError):
            d.band_from_score(5, (6, 4, 8))


# --------------------------------------------------------------------------
# Band label <-> ordinal round trips
# --------------------------------------------------------------------------


def test_band_label_ordinal_round_trip():
    for i, label in enumerate(config.ASSURE_BANDS, start=1):
        assert d.assure_ordinal(label) == i
        assert d.assure_label(i) == label
    for i, label in enumerate(config.INSPIRE_BANDS, start=1):
        assert d.inspire_ordinal(label) == i
        assert d.inspire_label(i) == label


@pytest.mark.parametrize("bad", [0, 5, -1])
def test_label_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        d.assure_label(bad)


# --------------------------------------------------------------------------
# high / low rollup and quadrant
# --------------------------------------------------------------------------


class TestHighLow:
    def test_threshold(self):
        assert d.is_high(3) is True
        assert d.is_high(4) is True
        assert d.is_high(2) is False
        assert d.is_high(1) is False


class TestQuadrant:
    def test_all_four_quadrants(self):
        assert d.quadrant(4, 4) == "High Inspire · High Assure"
        assert d.quadrant(3, 3) == "High Inspire · High Assure"
        assert d.quadrant(4, 2) == "High Inspire · Low Assure"
        assert d.quadrant(3, 1) == "High Inspire · Low Assure"
        assert d.quadrant(2, 4) == "Low Inspire · High Assure"
        assert d.quadrant(1, 3) == "Low Inspire · High Assure"
        assert d.quadrant(2, 2) == "Low Inspire · Low Assure"
        assert d.quadrant(1, 1) == "Low Inspire · Low Assure"

    def test_every_result_is_a_configured_name(self):
        for i in (1, 2, 3, 4):
            for a in (1, 2, 3, 4):
                assert d.quadrant(i, a) in config.QUADRANTS

    def test_low_value_is_never_produced(self):
        results = {d.quadrant(i, a) for i in range(1, 5) for a in range(1, 5)}
        assert not any("value" in r.lower() or "quality" in r.lower() for r in results)


# --------------------------------------------------------------------------
# Sequence position
# --------------------------------------------------------------------------


class TestPosition:
    def test_early(self):
        assert d.position(1, 4) == "early"
        assert d.position(1, 2) == "early"

    def test_final(self):
        assert d.position(4, 4) == "final"
        assert d.position(2, 2) == "final"

    def test_mid(self):
        assert d.position(2, 4) == "mid"
        assert d.position(3, 4) == "mid"

    def test_single_when_only_one_task(self):
        assert d.position(1, 1) == "single"

    def test_single_when_number_missing(self):
        assert d.position(None, 4) == "single"

    def test_single_when_max_missing_or_small(self):
        assert d.position(1, None) == "single"
        assert d.position(1, 0) == "single"


# --------------------------------------------------------------------------
# Action tier from the weaker axis
# --------------------------------------------------------------------------


class TestActionTier:
    @pytest.mark.parametrize(
        "weaker, expected",
        [(4, "Retain"), (3, "Enhance"), (2, "Targeted redesign"), (1, "Full redesign")],
    )
    def test_tiers(self, weaker, expected):
        assert d.action_tier(weaker) == expected

    def test_driven_by_weaker_axis(self):
        # strong on one axis, weak on the other -> weak one drives it
        assert d.action_tier(min(4, 2)) == "Targeted redesign"
        assert d.action_tier(min(1, 4)) == "Full redesign"


# --------------------------------------------------------------------------
# Position weighting — the softening cases
# --------------------------------------------------------------------------


class TestPositionWeightingSoftens:
    def test_early_weak_assure_is_softened(self):
        # axis-only: min(assure=1, inspire=3) -> Full redesign
        # early + weak assure -> assure treated as 2 -> min(2,3) -> Targeted
        tier, reason = d.apply_position_weighting(assure_band=1, inspire_band=3, pos="early")
        assert tier == "Targeted redesign"
        assert reason == config.REASON_EARLY_SOFTEN_ASSURE

    def test_final_weak_inspire_is_softened(self):
        tier, reason = d.apply_position_weighting(assure_band=3, inspire_band=1, pos="final")
        assert tier == "Targeted redesign"
        assert reason == config.REASON_FINAL_SOFTEN_INSPIRE

    def test_softening_caps_at_band_4(self):
        # early, assure=2 (<= 2) weaker than inspire=4 -> assure_eff = 3, not 5
        tier, reason = d.apply_position_weighting(assure_band=2, inspire_band=4, pos="early")
        assert tier == "Enhance"          # min(3, 4) -> band 3
        assert reason == config.REASON_EARLY_SOFTEN_ASSURE


class TestPositionWeightingMustNotSoften:
    def test_early_weak_inspire_stays_harsh(self):
        # inspiration is never softened at an early task
        tier, reason = d.apply_position_weighting(assure_band=3, inspire_band=1, pos="early")
        assert tier == "Full redesign"
        assert reason is None

    def test_final_weak_assure_stays_harsh(self):
        # assurance is never softened at a final task
        tier, reason = d.apply_position_weighting(assure_band=1, inspire_band=3, pos="final")
        assert tier == "Full redesign"
        assert reason is None

    def test_early_assure_not_weaker_is_not_softened(self):
        # assure == inspire -> not the strictly weaker axis -> no change
        tier, reason = d.apply_position_weighting(assure_band=2, inspire_band=2, pos="early")
        assert tier == "Targeted redesign"
        assert reason is None

    def test_early_assure_weak_but_still_high_band_not_softened(self):
        # assure = 3 is not <= 2, so nothing to soften
        tier, reason = d.apply_position_weighting(assure_band=3, inspire_band=4, pos="early")
        assert tier == "Enhance"
        assert reason is None

    def test_mid_is_never_softened(self):
        tier, reason = d.apply_position_weighting(assure_band=1, inspire_band=3, pos="mid")
        assert tier == "Full redesign"
        assert reason is None

    def test_single_is_never_softened(self):
        tier, reason = d.apply_position_weighting(assure_band=1, inspire_band=3, pos="single")
        assert tier == "Full redesign"
        assert reason is None


# --------------------------------------------------------------------------
# resolve_band — the seeding rule
# --------------------------------------------------------------------------


class TestResolveBand:
    A = config.ASSURE_BANDS

    def _resolve(self, override, score, *, confirmed=False, rescore=False):
        return d.resolve_band(
            override, score, self.A,
            confirmed=confirmed, rescore=rescore, cut_points=None,
        )

    def test_human_override_wins_over_score(self):
        n, src = self._resolve("Assured", 2.0)
        assert (n, src) == (4, "human")

    def test_score_used_when_no_override(self):
        n, src = self._resolve(None, 6.0)
        assert (n, src) == (3, "round1")

    def test_manual_when_nothing_to_go_on(self):
        n, src = self._resolve(None, None)
        assert (n, src) == (None, "manual")

    def test_rescore_prefers_score_over_override(self):
        n, src = self._resolve("Assured", 2.0, rescore=True)
        assert (n, src) == (1, "round1")

    def test_confirmed_row_keeps_stored_band_even_when_rescoring(self):
        n, src = self._resolve("Assured", 2.0, confirmed=True, rescore=True)
        assert (n, src) == (4, "human")


# --------------------------------------------------------------------------
# derive_task — end to end
# --------------------------------------------------------------------------


class TestDeriveTask:
    def test_scores_only_full_pipeline(self):
        r = d.derive_task(
            assure_score=3, inspire_score=8,
            assessment_number=1, subject_max_number=3,
            weight_by_position=False,
        )
        assert r.assure_band == "Not Assured"
        assert r.inspire_band == "Inspiring"
        assert r.quadrant == "High Inspire · Low Assure"
        assert r.position == "early"
        assert r.action_axis_only == "Full redesign"
        assert r.action_suggested == "Full redesign"
        assert r.position_changed_action is False
        assert r.needs_manual is False

    def test_position_weighting_changes_the_recommendation(self):
        r = d.derive_task(
            assure_score=3, inspire_score=8,           # assure band 1, inspire band 4
            assessment_number=1, subject_max_number=3,  # early
            weight_by_position=True,
        )
        assert r.action_axis_only == "Full redesign"
        assert r.action_suggested == "Targeted redesign"
        assert r.position_changed_action is True
        assert r.action_reason == config.REASON_EARLY_SOFTEN_ASSURE

    def test_needs_manual_when_a_score_and_band_are_both_missing(self):
        r = d.derive_task(
            assure_score=None, inspire_score=7,
            assessment_number=2, subject_max_number=3,
        )
        assert r.needs_manual is True
        assert r.quadrant is None
        assert r.action_suggested is None
        assert r.position == "mid"          # position still derivable

    def test_confirmed_row_is_not_rescored(self):
        r = d.derive_task(
            assure_band_override="Assured",
            inspire_band_override="Inspiring",
            assure_score=2, inspire_score=2,   # would band to 1/1 if used
            assessment_number=3, subject_max_number=3,
            confirmed=True, rescore=True,
        )
        assert r.assure_band == "Assured"
        assert r.inspire_band == "Inspiring"
        assert r.assure_source == "human"
        assert r.inspire_source == "human"
        assert r.quadrant == "High Inspire · High Assure"
        assert r.action_suggested == "Retain"

    def test_human_band_beats_score_by_default(self):
        r = d.derive_task(
            assure_band_override="Contributes to Assurance",
            assure_score=1,
            inspire_score=7,
            assessment_number=2, subject_max_number=4,
        )
        assert r.assure_band == "Contributes to Assurance"
        assert r.assure_source == "human"
        assert r.inspire_source == "round1"

    def test_single_task_never_softened_end_to_end(self):
        r = d.derive_task(
            assure_score=2, inspire_score=8,             # assure band 1, inspire band 4
            assessment_number=1, subject_max_number=1,   # single
            weight_by_position=True,
        )
        assert r.position == "single"
        # weaker axis is band 1 -> Full redesign, and "single" is never softened
        assert r.action_axis_only == r.action_suggested == "Full redesign"
        assert r.position_changed_action is False
