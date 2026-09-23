"""A staff member's workload over a year, against their annual target.

Pure functions over DataFrames of stored strings — no Streamlit, no Sheet.

How a person's year is worked out:
  * target   = their role's DI hrs/wk × FTE × 36 weeks (576 h for a
               full-time Teacher);
  * teaching = for every block in the Calendar, the DI hrs/wk of their
               teaching lines in that block × the block's teaching weeks
               (a line for block "All" counts in each block);
  * duties   = higher duties and other duties, in hours:
                 - acting in a more senior role: the DI hours that role
                   doesn't teach, per week (Teacher → Subject Coordinator
                   16 → 10 = 6 h/wk), × FTE;
                 - anything else (or acting role N/A): the hrs/wk entered;
               × the weeks it covers (the whole block, or the "Weeks" given,
               counted from the block's start);
  * total    = teaching + duties — the projected year, compared with the
               target: within ±5 % is on track, otherwise off track (over or
               under).
  * to date  = the same sums, counting only the weeks of each block that
               have passed by the "as at" date; left = target − to date.

Teaching in several disciplines is simply several lines; everything adds up
to one row per person.
"""

from __future__ import annotations

import pandas as pd

import workload_config as cfg

STATUS_ON = "🟢 On track"
STATUS_OVER = "🟠 Off track — over"
STATUS_UNDER = "🟡 Off track — under"
STATUS_CASUAL = "⚪ Casual"
STATUSES = [STATUS_ON, STATUS_OVER, STATUS_UNDER, STATUS_CASUAL]

DUTIES = "HDA / other duties"


def num(value) -> float:
    """A stored cell as a number; blank / junk counts as 0."""
    try:
        v = float(str(value).strip())
    except ValueError:
        return 0.0
    return 0.0 if pd.isna(v) else v


def fte(value) -> float:
    v = num(value)
    return v if 0 < v <= 1 else 1.0


def weekly_di(role: str) -> float | None:
    """Full-time DI hrs/wk for the role. None = no limit (casual)."""
    return cfg.ROLES.get(role, cfg.ROLES[cfg.DEFAULT_ROLE])


def role_limit(role: str, fte_: float) -> float | None:
    """Full-time DI hrs/wk for the role, scaled by FTE. None = no limit (casual)."""
    di = weekly_di(role)
    return None if di is None else di * fte_


def annual_target(role: str, fte_: float) -> float | None:
    limit = role_limit(role, fte_)
    return None if limit is None else limit * cfg.ANNUAL_WEEKS


def in_block(line_block: str, block: str) -> bool:
    b = str(line_block).strip()
    return b in ("", cfg.ALL_BLOCKS) or b == block


def session_of(year: int, session: str) -> str:
    return f"{year % 100:02d} {session}"


def year_sessions(yy: str) -> list[str]:
    return [f"{yy} {s}" for s in cfg.SESSIONS]


def in_year(session, yy: str) -> bool:
    return str(session).startswith(f"{yy} ")


def default_session(today: pd.Timestamp | None = None) -> str:
    """Summer Dec–Feb, Autumn Mar–Jun, Spring Jul–Nov. Summer is labelled by
    calendar year (Dec 2026 → 26 SUM, Jan 2027 → 27 SUM)."""
    t = today or pd.Timestamp.today()
    if t.month >= 12 or t.month <= 2:
        return session_of(t.year, "SUM")
    return session_of(t.year, "AUT" if t.month <= 6 else "SPR")


def calendar_fill(calendar: pd.DataFrame, yy: str) -> tuple[list[dict], dict[str, dict]]:
    """What the Calendar button does for year `yy`: (new rows for the year's
    blocks not yet in the Calendar, {ID: values} for existing rows whose start
    date or weeks are blank and are in cfg.BLOCK_DATES). Not saved."""
    have = {(s, str(b).strip()): i for i, s, b in zip(calendar["ID"], calendar["Session"], calendar["Block"])}
    new, updates = [], {}
    for s in year_sessions(yy):
        for b in cfg.SESSION_BLOCKS[s.partition(" ")[2]]:
            start, weeks = cfg.BLOCK_DATES.get((s, b), ("", ""))
            if (s, b) not in have:
                new.append({"Session": s, "Block": b, "Start date": start, "Teaching weeks": str(weeks)})
    for _, r in calendar[calendar["Session"].map(lambda s: in_year(s, yy))].iterrows():
        known = cfg.BLOCK_DATES.get((r["Session"], str(r["Block"]).strip()))
        if not known:
            continue
        vals = {}
        if not str(r["Start date"]).strip():
            vals["Start date"] = known[0]
        if not str(r["Teaching weeks"]).strip():
            vals["Teaching weeks"] = str(known[1])
        if vals:
            updates[r["ID"]] = vals
    return new, updates


def session_sort_key(s: str) -> tuple[int, int]:
    yy, _, name = str(s).partition(" ")
    order = cfg.SESSIONS.index(name) if name in cfg.SESSIONS else 9
    return (int(yy) if yy.isdigit() else 0, order)


# --------------------------------------------------------------------------
# calendar
# --------------------------------------------------------------------------


def calendar_blocks(calendar: pd.DataFrame, yy: str) -> list[dict]:
    """The year's blocks in order: {Session, Block, start (Timestamp | None), weeks}."""
    rows = []
    for _, r in calendar[calendar["Session"].map(lambda s: in_year(s, yy))].iterrows():
        start = pd.to_datetime(r["Start date"], errors="coerce")
        rows.append({"Session": r["Session"], "Block": str(r["Block"]).strip(),
                     "start": None if pd.isna(start) else start, "weeks": num(r["Teaching weeks"])})
    return sorted(rows, key=lambda r: (session_sort_key(r["Session"]), r["Block"]))


def elapsed_weeks(start: pd.Timestamp | None, weeks: float, as_at: pd.Timestamp) -> float:
    """Teaching weeks of a block that have passed by `as_at` (inclusive)."""
    if start is None or weeks <= 0:
        return 0.0
    days = (pd.Timestamp(as_at).normalize() - start.normalize()).days + 1
    return min(max(days / 7, 0.0), weeks)


def calendar_gaps(allocations: pd.DataFrame, adjustments: pd.DataFrame,
                  calendar: pd.DataFrame, yy: str) -> list[str]:
    """Session · block pairs with teaching or duties this year but no weeks in
    the Calendar — their hours count as zero until the Calendar is filled in."""
    have = {(r["Session"], r["Block"]) for r in calendar_blocks(calendar, yy) if r["weeks"] > 0}
    used = set()
    for t in (allocations, adjustments):
        for s, b in zip(t["Session"], t["Block"]):
            if in_year(s, yy):
                every = cfg.SESSION_BLOCKS.get(str(s).partition(" ")[2], cfg.BLOCKS)
                for blk in (every if str(b).strip() in ("", cfg.ALL_BLOCKS) else [str(b).strip()]):
                    used.add((s, blk))
    return [f"{s} B{b}" for s, b in sorted(used - have, key=lambda sb: (session_sort_key(sb[0]), sb[1]))]


# --------------------------------------------------------------------------
# one person's year
# --------------------------------------------------------------------------


def _acting(adj_row) -> str | None:
    """The role acted in, if this is a higher-duties row with a real one."""
    acting = str(adj_row["Acting role"]).strip()
    if adj_row["Type"] == cfg.HIGHER_DUTIES and acting in cfg.ROLES and acting != cfg.NOT_ACTING:
        return acting
    return None


def duty_hours_per_week(adj_row, role: str, fte_: float) -> float:
    """Hours/week an adjustment takes out of teaching."""
    acting = _acting(adj_row)
    if acting:
        own, act = weekly_di(role), weekly_di(acting)
        if own is not None and act is not None:
            return max(0.0, own - act) * fte_
    return num(adj_row["DI relief hrs/wk"])


def describe_adjustment(a) -> str:
    acting = _acting(a)
    what = f"Acting {acting}" if acting else f"{a['Type']} {num(a['DI relief hrs/wk']):g}h/wk"
    where = a["Session"] + (f" B{a['Block']}" if str(a["Block"]).strip() not in ("", cfg.ALL_BLOCKS) else "")
    weeks = f", {num(a['Weeks']):g} wk" if num(a["Weeks"]) > 0 else ""
    return f"{what} ({where}{weeks})"


def status(total: float, target: float | None) -> str:
    if target is None:
        return STATUS_CASUAL
    band = target * cfg.ON_TRACK_TOLERANCE
    if total > target + band + 1e-9:
        return STATUS_OVER
    if total < target - band - 1e-9:
        return STATUS_UNDER
    return STATUS_ON


def person_year(
    staff: dict,
    allocations: pd.DataFrame,
    adjustments: pd.DataFrame,
    blocks: list[dict],
    as_at: pd.Timestamp,
) -> dict:
    """Everything the dashboard shows for one person over the year whose
    Calendar blocks are `blocks`. The tables may be whole; they're filtered here."""
    name = staff["Staff"]
    role = staff.get("Role", "")
    f = fte(staff.get("FTE"))
    sessions = {b["Session"] for b in blocks}

    alloc = allocations[(allocations["Staff"] == name) & allocations["Session"].isin(sessions)]
    adj = adjustments[(adjustments["Staff"] == name) & adjustments["Session"].isin(sessions)]

    teaching = teaching_done = duties = duties_done = 0.0
    by_discipline: dict[str, float] = {}
    by_session: dict[str, float] = {s: 0.0 for s in cfg.SESSIONS}
    for blk in blocks:
        s, b, w = blk["Session"], blk["Block"], blk["weeks"]
        done = elapsed_weeks(blk["start"], w, as_at)
        sname = s.partition(" ")[2]
        for _, r in alloc[alloc["Session"] == s].iterrows():
            if not in_block(r["Block"], b):
                continue
            h = num(r["DI hrs/wk"])
            teaching += h * w
            teaching_done += h * done
            d = r["Discipline"] or "(none)"
            by_discipline[d] = by_discipline.get(d, 0.0) + h * w
            by_session[sname] += h * w
        for _, a in adj[adj["Session"] == s].iterrows():
            if not in_block(a["Block"], b):
                continue
            aw = min(num(a["Weeks"]), w) if num(a["Weeks"]) > 0 else w
            h = duty_hours_per_week(a, role, f)
            duties += h * aw
            duties_done += h * min(done, aw)
            by_session[sname] += h * aw

    total = teaching + duties
    to_date = teaching_done + duties_done
    weeks = sum(b["weeks"] for b in blocks)
    target = annual_target(role, f)
    return {
        "Staff": name,
        "Role": role,
        "FTE": f,
        "Supervisor": staff.get("Supervisor", ""),
        "Status": status(total, target),
        "Target": target,
        "Teaching": teaching,
        "Duties": duties,
        "Total": total,
        "Variance": None if target is None else total - target,
        "To date": to_date,
        "Left": None if target is None else target - to_date,
        "Avg hrs/wk": total / weeks if weeks else 0.0,
        **{s: by_session[s] for s in cfg.SESSIONS},
        "by_discipline": by_discipline,
        "Disciplines": " · ".join(
            f"{d} {h:g}h" for d, h in sorted(by_discipline.items(), key=lambda kv: -kv[1])
        ),
        "Acting": ", ".join(sorted({a for a in (_acting(r) for _, r in adj.iterrows()) if a})),
        "Adjustments": "; ".join(describe_adjustment(a) for _, a in adj.iterrows()),
    }


def summarise_year(
    staff: pd.DataFrame,
    allocations: pd.DataFrame,
    adjustments: pd.DataFrame,
    calendar: pd.DataFrame,
    yy: str,
    as_at: pd.Timestamp,
) -> pd.DataFrame:
    """One row per active staff member for the year."""
    blocks = calendar_blocks(calendar, yy)
    active = staff[staff["Active"].str.upper() != "FALSE"]
    rows = [person_year(s, allocations, adjustments, blocks, as_at) for s in active.to_dict("records")]
    return pd.DataFrame(rows)


def orphans(staff: pd.DataFrame, table: pd.DataFrame) -> list[str]:
    """Names on allocation / adjustment rows that aren't on the staff list."""
    known = set(staff["Staff"])
    return sorted({n for n in table["Staff"] if n and n not in known})
