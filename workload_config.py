"""Contestable values for Workload Management.

Everything is in hours of Direct Instruction (DI) per week during a teaching
session — the unit the WSU The College Enterprise Agreement 2022 uses.
Core Duties run 1:1 with DI in both schedules, so DI hours are the load a
supervisor actually allocates; the rest of the 35-hour week follows from it.

Sources (The College EA 2022):
  * Schedule B 2.7  — weekly time allocation for a Teacher: 16 DI hrs
                      (+16 Core Duties, 3 Other Duties)
  * Schedule B 2.9  — DI hours may vary session to session, averaging out
                      over the academic year
  * 22.13 / 22.14   — the schedules set the *maximum* DI hours
  * 22.16           — workloads take the Employee's fraction (FTE) into account
  * 21              — higher duties
  * 24.1            — the workload clause doesn't apply to casuals

If a limit changes (new agreement, local practice), change it here only.
"""

from __future__ import annotations

# --- Roles -------------------------------------------------------------------
# The College's four staff types. role -> DI hrs/wk maximum for a full-time
# person (scaled by FTE); None = no workload limit (casuals are paid by the
# hour; 24.1).
#
# Teacher (Ongoing) is the Sch B 2.7 Teacher figure. The coordinator roles
# are the current names for the EA's older ones — Subject Coordinator ≈ First
# Year Experience Coordinator, Program Coordinator ≈ Learning and Teaching
# Coordinator — at the College's own limits (confirmed by Josiah, 2026-09-19),
# not the EA table's 10 / 6.
ROLES: dict[str, float | None] = {
    "Program Coordinator": 8,        # College figure (EA equivalent: L&T Coordinator)
    "Subject Coordinator": 12,       # College figure (EA equivalent: FYE Coordinator)
    "Teacher (Ongoing)": 16,         # Sch B 2.7
    "Teacher (Casual)": None,        # 24.1 — no workload clause
}
STAFF_ROLES: list[str] = list(ROLES)
# Higher duties = acting in one of the coordinator roles.
ACTING_ROLES: list[str] = ["Program Coordinator", "Subject Coordinator"]
DEFAULT_ROLE = "Teacher (Ongoing)"

# --- Sessions ----------------------------------------------------------------
# Same naming as WSTUCReports: "26 AUT", "26 SPR", "26 SUM"; four blocks each.
SESSIONS: list[str] = ["AUT", "SPR", "SUM"]
BLOCKS: list[str] = ["1", "2", "3", "4"]
ALL_BLOCKS = "All"
BLOCK_OPTIONS: list[str] = [ALL_BLOCKS] + BLOCKS

# --- Disciplines -------------------------------------------------------------
# Starting list only — anything already in the Sheet is offered as well.
DISCIPLINES: list[str] = [
    "Academic Literacies",
    "Arts",
    "Business",
    "Computing & IT",
    "Engineering",
    "Health Science",
    "Mathematics",
    "Science",
]

# --- Load adjustments --------------------------------------------------------
HIGHER_DUTIES = "Higher duties (acting)"
ADJUSTMENT_TYPES: list[str] = [
    HIGHER_DUTIES,                                  # 21 — cap becomes the acting role's
    "Curriculum development relief",                # Sch B 2.11(d) — 1 h DI per 2 h of work
    "Travel time between campuses",                 # 28.10 — reduces contact hours
    "Other approved release",
]
ADJUSTMENT_HELP = (
    "Higher duties: pick the acting role — its DI limit replaces the usual one "
    "for those blocks (21). Anything else: enter the DI hours/week it frees up. "
    "Curriculum development: 1 h DI relief per 2 h of work (Sch B 2.11(d)). "
    "Travel time counts as a reduction in contact hours (28.10)."
)

# --- Status thresholds -------------------------------------------------------
# Within this many hours under the limit counts as "Full" rather than "Spare".
FULL_WITHIN_HOURS: float = 1.0
