"""Contestable values for the IA Mapping tool.

Everything a reviewer might argue about lives here, not buried in code:
band labels, the numeric cut points, quadrant names, action tiers, and the
default for position weighting. `derivation.py` imports from this module and
nothing else.
"""

from __future__ import annotations

# --- Band labels -----------------------------------------------------------
# Order is meaningful: index 0 is the weakest level, index 3 the strongest.
# The 1-4 ordinal used throughout derivation is (index + 1).
#
# Assure wording is verbatim WSU / IA language and must not be paraphrased
# (see the proposal, section 2.2 and the "drift in official wording" risk).
ASSURE_BANDS: list[str] = [
    "Not Assured",
    "Potential Assurance",
    "Contributes to Assurance",
    "Assured",
]

# Inspire wording follows the IA framing, judged on FIRE
# (Formative, Instant feedback, Repeatable, Evaluative judgement).
INSPIRE_BANDS: list[str] = [
    "Not Inspiring",
    "Potential to Inspire",
    "Contributes to Inspiration",
    "Inspiring",
]

# --- Quadrant names ------------------------------------------------------- -
# Two independent axes, each collapsed to high/low, then crossed.
# These four names are the headline reporting view (proposal section 2.4).
# The single-label scheme ("Inspire" / "Assure" / "Inspire & Assure" /
# "Low value") is retired and is never produced by this tool.
QUADRANTS: list[str] = [
    "High Inspire · High Assure",
    "High Inspire · Low Assure",
    "Low Inspire · High Assure",
    "Low Inspire · Low Assure",
]

# --- Redesign action tiers ---------------------------------------------- ---
# Driven by the weaker of the two axis bands (proposal section 2.5).
ACTIONS: list[str] = [
    "Retain",              # weaker axis == Assured / Inspiring   (band 4)
    "Enhance",             # weaker axis == Contributes           (band 3)
    "Targeted redesign",   # weaker axis == Potential             (band 2)
    "Full redesign",       # either axis == Not                   (band 1)
]

# Structured effort field, shown when a task is not in the top tier.
EFFORT_LEVELS: list[str] = ["Low", "Medium", "High"]

# --- Numeric banding ---------------------------------------------------- ---
# Round-1 scores are 1-10. A score is banded with cut points (low, mid, high):
#   >= high -> 4, >= mid -> 3, >= low -> 2, else 1
# Default (4, 6, 8). Exposed as a sidebar control in the app.
DEFAULT_CUT_POINTS: tuple[int, int, int] = (4, 6, 8)

# --- Position weighting --------------------------------------------------- -
# Whether the suggested action is softened by the task's place in the
# subject's assessment sequence. NOT part of the endorsed proposal - an
# extension - so it is a toggle and this is only its default.
WEIGHT_BY_POSITION_DEFAULT: bool = True

# Reason strings surfaced when position weighting changes the recommendation.
REASON_EARLY_SOFTEN_ASSURE: str = (
    "Early task — low assurance is acceptable at a formative / "
    "checkpoint stage."
)
REASON_FINAL_SOFTEN_INSPIRE: str = (
    "Final task — inspiration isn't the priority here; assurance is."
)

# --- Axis high/low rollup --------------------------------------------------
# A band of this ordinal or higher counts as "high" on its axis.
HIGH_BAND_THRESHOLD: int = 3
