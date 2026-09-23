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
# The College's staff types. role -> DI hrs/wk for a full-time person (scaled
# by FTE); None = no workload limit (casuals are paid by the hour; 24.1).
#
# Teacher (Ongoing) is the Sch B 2.7 Teacher figure. Subject Coordinator ≈ the
# EA's First Year Experience Coordinator and Program Coordinator ≈ its L&T
# Coordinator, at the EA table's 10 / 6 (confirmed by Josiah, 2026-09-23;
# replaces the 12 / 8 used before). Associate Director teaches no DI.
ROLES: dict[str, float | None] = {
    "Associate Director": 0,
    "Program Coordinator": 6,        # EA equivalent: L&T Coordinator
    "Subject Coordinator": 10,       # EA equivalent: FYE Coordinator
    "Teacher (Ongoing)": 16,         # Sch B 2.7
    "Teacher (Casual)": None,        # 24.1 — no workload clause
}
STAFF_ROLES: list[str] = list(ROLES)
DEFAULT_ROLE = "Teacher (Ongoing)"

# Higher duties = acting in a more senior role. The DI hours the acting role
# doesn't teach become higher-duties hours: Teacher → Subject Coordinator
# 16 → 10 (6 h HDA), Subject → Program Coordinator 10 → 6 (4 h), Program
# Coordinator → Associate Director 6 → 0 (6 h). N/A = no acting role (e.g.
# curriculum development): enter the hours/week instead.
NOT_ACTING = "N/A"
ACTING_ROLES: list[str] = [NOT_ACTING, "Subject Coordinator", "Program Coordinator", "Associate Director"]

# --- The year ----------------------------------------------------------------
# A full-time Teacher's year: 16 DI hrs/wk × 36 teaching weeks = 576 h. The
# annual target for anyone is their role's hrs/wk × FTE × this. Block dates
# and lengths come from the Calendar tab.
ANNUAL_WEEKS: float = 36

# Projected year total within this fraction of the target = on track.
ON_TRACK_TOLERANCE: float = 0.05

# --- Sessions ----------------------------------------------------------------
# Same naming as WSTUCReports: "26 AUT", "26 SPR", "26 SUM".
SESSIONS: list[str] = ["AUT", "SPR", "SUM"]
BLOCKS: list[str] = ["1", "2", "3", "4"]
ALL_BLOCKS = "All"
BLOCK_OPTIONS: list[str] = [ALL_BLOCKS] + BLOCKS

# Blocks each session has. Summer is labelled by calendar year: "26 SUM"
# block 1 runs Nov–Dec 2026, "27 SUM" block 2 Jan–Feb 2027.
SESSION_BLOCKS: dict[str, list[str]] = {"AUT": ["1", "2", "3", "4"], "SPR": ["1", "2", "3", "4"],
                                        "SUM": ["1", "2"]}

# Known block dates: (session, block) -> (start Monday, teaching weeks). The
# Calendar tab's button fills these in; the Calendar itself is what counts.
BLOCK_DATES: dict[tuple[str, str], tuple[str, int]] = {
    ("26 SPR", "1"): ("2026-07-20", 4),
    ("26 SPR", "2"): ("2026-08-17", 4),
    ("26 SPR", "3"): ("2026-09-21", 4),
    ("26 SPR", "4"): ("2026-10-19", 4),
    ("26 SUM", "1"): ("2026-11-23", 4),
    ("27 SUM", "2"): ("2027-01-11", 4),
    ("27 AUT", "1"): ("2027-03-01", 4),
    ("27 AUT", "2"): ("2027-03-29", 4),
    ("27 AUT", "3"): ("2027-05-03", 4),
    ("27 AUT", "4"): ("2027-05-31", 4),
    ("27 SPR", "1"): ("2027-07-19", 4),
    ("27 SPR", "2"): ("2027-08-16", 4),
    ("27 SPR", "3"): ("2027-09-20", 4),
    ("27 SPR", "4"): ("2027-10-18", 4),
}

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
    HIGHER_DUTIES,                                  # 21
    "Curriculum development relief",                # Sch B 2.11(d) — 1 h DI per 2 h of work
    "Travel time between campuses",                 # 28.10 — reduces contact hours
    "Other approved release",
]
ADJUSTMENT_HELP = (
    "Higher duties: pick the acting role — the DI hours it doesn't teach count as "
    "higher-duties hours (e.g. Teacher acting as Subject Coordinator: 16 → 10, so 6 h/wk). "
    "Anything else, or acting role N/A: enter the hours/week it takes. "
    "Curriculum development: 1 h DI relief per 2 h of work (Sch B 2.11(d)). "
    "Travel time counts as a reduction in contact hours (28.10). "
    "Weeks: leave blank for the whole block, or enter how many weeks of the block it covers "
    "(counted from the block's start)."
)
