"""Teaching load vs limit, per staff member per session and block.

Pure functions over DataFrames of stored strings — no Streamlit, no Sheet.

How a person's week is worked out, for one block of one session:
  * load  = the DI hours/week of every allocation in that block (an
            allocation for block "All" counts in each of the four blocks);
  * limit = their role's DI maximum × FTE — or, if they're acting in higher
            duties for that block, the acting role's maximum × FTE — minus any
            relief hours (curriculum development, travel, ...),
            never below zero.

The session figure is the average over its four blocks. Being over in one
block but not on average is a "peak", not an overload: the EA lets DI hours
vary and average out (Sch B 2.9).
"""

from __future__ import annotations

import pandas as pd

import workload_config as cfg

STATUS_OVER = "⛔ Over"
STATUS_PEAK = "⚠ Peak"
STATUS_FULL = "✅ Full"
STATUS_SPARE = "🟦 Spare"
STATUS_CASUAL = "Casual"


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


def role_limit(role: str, fte_: float) -> float | None:
    """Full-time DI max for the role, scaled by FTE. None = no limit (casual)."""
    di = cfg.ROLES.get(role, cfg.ROLES[cfg.DEFAULT_ROLE])
    return None if di is None else di * fte_


def in_block(line_block: str, block: str) -> bool:
    b = str(line_block).strip()
    return b in ("", cfg.ALL_BLOCKS) or b == block


def session_of(year: int, session: str) -> str:
    return f"{year % 100:02d} {session}"


def default_session(today: pd.Timestamp | None = None) -> str:
    """Autumn Feb–Jun, Spring Jul–Nov, Summer Dec–Jan."""
    t = today or pd.Timestamp.today()
    if t.month >= 12:
        return session_of(t.year + 1, "SUM")   # summer belongs to the coming year
    if t.month == 1:
        return session_of(t.year, "SUM")
    return session_of(t.year, "AUT" if t.month <= 6 else "SPR")


def session_sort_key(s: str) -> tuple[int, int]:
    yy, _, name = str(s).partition(" ")
    order = cfg.SESSIONS.index(name) if name in cfg.SESSIONS else 9
    return (int(yy) if yy.isdigit() else 0, order)


# --------------------------------------------------------------------------


def person_session(
    staff: dict,
    allocations: pd.DataFrame,
    adjustments: pd.DataFrame,
    session: str,
) -> dict:
    """Everything the dashboard shows for one person in one session.

    `allocations` / `adjustments` may be the whole tables; they're filtered here."""
    name = staff["Staff"]
    f = fte(staff.get("FTE"))
    base = role_limit(staff.get("Role", ""), f)

    alloc = allocations[(allocations["Staff"] == name) & (allocations["Session"] == session)]
    adj = adjustments[(adjustments["Staff"] == name) & (adjustments["Session"] == session)]

    loads, limits, acting = {}, {}, set()
    for b in cfg.BLOCKS:
        loads[b] = sum(num(h) for h, lb in zip(alloc["DI hrs/wk"], alloc["Block"]) if in_block(lb, b))
        limit = base
        relief = 0.0
        for _, a in adj.iterrows():
            if not in_block(a["Block"], b):
                continue
            if a["Type"] == cfg.HIGHER_DUTIES and a["Acting role"] in cfg.ROLES:
                limit = role_limit(a["Acting role"], f)
                acting.add(a["Acting role"])
            else:
                relief += num(a["DI relief hrs/wk"])
        limits[b] = None if limit is None else max(0.0, limit - relief)

    avg_load = sum(loads.values()) / len(cfg.BLOCKS)
    by_discipline: dict[str, float] = {}
    for _, r in alloc.iterrows():
        share = sum(in_block(r["Block"], b) for b in cfg.BLOCKS) / len(cfg.BLOCKS)
        d = r["Discipline"] or "(none)"
        by_discipline[d] = by_discipline.get(d, 0.0) + num(r["DI hrs/wk"]) * share

    out = {
        "Staff": name,
        "Role": staff.get("Role", ""),
        "FTE": f,
        "Supervisor": staff.get("Supervisor", ""),
        **{f"B{b}": loads[b] for b in cfg.BLOCKS},
        "Avg load": avg_load,
        "by_discipline": by_discipline,
        "Disciplines": " · ".join(
            f"{d} {h:g}h" for d, h in sorted(by_discipline.items(), key=lambda kv: -kv[1])
        ),
        "Acting": ", ".join(sorted(acting)),
        "Adjustments": "; ".join(
            f"{a['Type']}"
            + (f" as {a['Acting role']}" if a["Type"] == cfg.HIGHER_DUTIES else f" −{num(a['DI relief hrs/wk']):g}h")
            + (f" (block {a['Block']})" if a["Block"] not in ("", cfg.ALL_BLOCKS) else "")
            for _, a in adj.iterrows()
        ),
    }

    if any(v is None for v in limits.values()):
        out.update({"Limit": None, "Spare": None, "Used %": None, "Status": STATUS_CASUAL,
                    "Over blocks": ""})
        return out

    avg_limit = sum(limits.values()) / len(cfg.BLOCKS)
    over_blocks = [b for b in cfg.BLOCKS if loads[b] > limits[b] + 1e-9]
    spare = avg_limit - avg_load
    if avg_load > avg_limit + 1e-9:
        status = STATUS_OVER
    elif over_blocks:
        status = STATUS_PEAK
    elif spare <= cfg.FULL_WITHIN_HOURS:
        status = STATUS_FULL
    else:
        status = STATUS_SPARE
    out.update({
        "Limit": avg_limit,
        "Spare": spare,
        "Used %": (avg_load / avg_limit * 100) if avg_limit else (0.0 if not avg_load else 999.0),
        "Status": status,
        "Over blocks": ", ".join(over_blocks),
    })
    return out


def summarise(
    staff: pd.DataFrame,
    allocations: pd.DataFrame,
    adjustments: pd.DataFrame,
    session: str,
) -> pd.DataFrame:
    """One row per active staff member for the session."""
    active = staff[staff["Active"].str.upper() != "FALSE"]
    rows = [person_session(s, allocations, adjustments, session) for s in active.to_dict("records")]
    return pd.DataFrame(rows)


def year_average(staff_row: dict, allocations: pd.DataFrame, adjustments: pd.DataFrame, yy: str) -> tuple[float, float | None]:
    """(avg load, avg limit) over the year's sessions that have any allocation
    for this person — the Sch B 2.9 "averages out over the academic year" view."""
    sessions = sorted(
        {s for s in allocations.loc[allocations["Staff"] == staff_row["Staff"], "Session"]
         if str(s).startswith(f"{yy} ")},
        key=session_sort_key,
    )
    if not sessions:
        return 0.0, None
    per = [person_session(staff_row, allocations, adjustments, s) for s in sessions]
    if any(p["Limit"] is None for p in per):
        return sum(p["Avg load"] for p in per) / len(per), None
    return (
        sum(p["Avg load"] for p in per) / len(per),
        sum(p["Limit"] for p in per) / len(per),
    )


def orphans(staff: pd.DataFrame, table: pd.DataFrame) -> list[str]:
    """Names on allocation / adjustment rows that aren't on the staff list."""
    known = set(staff["Staff"])
    return sorted({n for n in table["Staff"] if n and n not in known})
