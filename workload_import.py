"""Read the L&T load tracking spreadsheet into Workload Management.

The spreadsheet ("Load tracking Staff Spreadsheet - Full year 2026 ...xlsx")
has a main sheet — one row per person: employee no, name, organisation unit,
required load, allocated hours, underload plan, details — and an "Underload
staff" sheet with summer teaching needed, likelihood and subject. Headers are
found by name, not position, so a later version with moved columns still reads.

Pure functions over DataFrames — the page shows the preview and saves.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

import pandas as pd

import workload_config as cfg
import workload_store as wstore

TITLES = {"mr", "mrs", "ms", "miss", "mx", "dr", "doctor", "prof", "professor", "assoc"}

# the fields a re-import refreshes on an existing Year plan row
PLAN_FIELDS = ["Target (h)", "Other allocated (h)", "Plan", "Summer hrs needed", "Likelihood", "Subject",
               "Notes"]


# --------------------------------------------------------------------------
# names
# --------------------------------------------------------------------------


def _words(s: str) -> list[str]:
    return [w for w in re.split(r"[^a-z']+", str(s).lower().replace("’", "'")) if w]


def split_name(name: str) -> tuple[str, list[str]]:
    """(surname, given names) from "Surname, Title Given …" or "Given … Surname"."""
    name = str(name).strip()
    if "," in name:
        surname, _, given = name.partition(",")
        given_words = [w for w in _words(given) if w not in TITLES]
        return " ".join(_words(surname)), given_words
    words = [w for w in _words(name) if w not in TITLES]
    if not words:
        return "", []
    return words[-1], words[:-1]


def display_name(name: str) -> str:
    """"Abboud, Ms Antoinette" → "Abboud, Antoinette" (titles dropped)."""
    name = str(name).strip()
    if "," not in name:
        return name
    surname, _, given = name.partition(",")
    kept = [w for w in given.split() if w.lower().strip(".") not in TITLES]
    return f"{surname.strip()}, {' '.join(kept)}".strip().rstrip(",")


def name_key(name: str) -> tuple[str, str]:
    surname, given = split_name(name)
    return surname, (given[0] if given else "")


def _emp(v) -> str:
    s = str(v).strip()
    if s.lower() in ("", "nan", "none"):
        return ""
    return s[:-2] if s.endswith(".0") else s


def _similar(a: tuple[str, str], b: tuple[str, str]) -> bool:
    """Same first name and near-identical surname (a typo), or the reverse."""
    sur = difflib.SequenceMatcher(None, a[0], b[0]).ratio()
    giv = difflib.SequenceMatcher(None, a[1], b[1]).ratio()
    return a != b and ((a[1] == b[1] and sur >= 0.8) or (a[0] == b[0] and giv >= 0.8))


# --------------------------------------------------------------------------
# reading the workbook
# --------------------------------------------------------------------------


def _num(v) -> float | None:
    try:
        f = float(str(v).strip())
    except ValueError:
        return None
    return None if pd.isna(f) else f


def _text(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


def _find_header(raw: pd.DataFrame, must: list[str]) -> int | None:
    for i in range(min(len(raw), 20)):
        cells = [_text(v).lower() for v in raw.iloc[i]]
        if all(any(c.startswith(m) for c in cells) for m in must):
            return i
    return None


def _columns(header: list[str], wanted: dict[str, list[str]]) -> dict[str, int]:
    """{field: column index} — the first header starting with any of the prefixes."""
    cells = [_text(h).lower() for h in header]
    out = {}
    for name, prefixes in wanted.items():
        for i, c in enumerate(cells):
            if any(c.startswith(p) for p in prefixes):
                out[name] = i
                break
    return out


MAIN_COLS = {
    "emp": ["employee no"],
    "name": ["name"],
    "unit": ["organisation unit", "organization unit"],
    "required": ["required load"],
    "allocated": ["allocated hours"],
    "summer": ["summer hours needed"],
    "plan": ["articulated plan"],
    "details": ["details"],
}
UNDER_COLS = {
    "emp": ["employee no"],
    "name": ["name"],
    "projected": ["projected to be met"],
    "summer": ["summer teaching needed"],
    "likelihood": ["likel"],
    "subject": ["subject"],
}


def _plan_value(v) -> str:
    s = _text(v).lower().replace("/", "")
    return {"yes": "Yes", "y": "Yes", "no": "No", "n": "No", "na": "N/A", "n a": "N/A"}.get(s, "")


def _likelihood(v) -> str:
    s = _text(v).lower()
    if s.startswith("confirm"):
        return "Confirmed"
    if s.startswith("possib"):
        return "Possible"
    if s.startswith("not"):
        return "Not likely"
    return ""


def _unit(v) -> str:
    s = _text(v)
    for d in cfg.DISCIPLINES:
        if d.lower() == s.lower():
            return d
    return s


@dataclass
class Parsed:
    people: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_workbook(file) -> Parsed:
    """Every person on the main sheet, with the underload sheet merged in."""
    # keep_default_na=False: "N/A" / "NA" are answers in this spreadsheet, not blanks
    sheets = pd.read_excel(file, sheet_name=None, header=None, dtype=object, keep_default_na=False)
    out = Parsed()

    main = under = None
    for name, raw in sheets.items():
        if main is None and (h := _find_header(raw, ["name", "required load"])) is not None:
            main = (name, raw, h)
        elif under is None and (h := _find_header(raw, ["name", "hours underloaded", "likel"])) is not None:
            under = (name, raw, h)
    if main is None:
        out.warnings.append("No sheet with 'Name' and 'Required load' headers — nothing to import.")
        return out

    _, raw, h = main
    cols = _columns(list(raw.iloc[h]), MAIN_COLS)
    for _, r in raw.iloc[h + 1:].iterrows():
        get = lambda k: r.iloc[cols[k]] if k in cols else None  # noqa: E731
        name = _text(get("name"))
        if not name or not split_name(name)[0]:
            continue
        details = _text(get("details"))
        out.people.append({
            "name": display_name(name),
            "source_name": name,
            "emp": _emp(get("emp")),
            "unit": _unit(get("unit")),
            "required": _num(get("required")),
            "allocated": _num(get("allocated")),
            "summer": _num(get("summer")),
            "plan": _plan_value(get("plan")),
            "likelihood": "",
            "subject": "",
            "details": details,
            "inactive": "resign" in details.lower(),
        })

    by_emp = {p["emp"]: p for p in out.people if p["emp"]}
    by_key = {name_key(p["source_name"]): p for p in out.people}

    if under is not None:
        sname, raw, h = under
        cols = _columns(list(raw.iloc[h]), UNDER_COLS)
        for _, r in raw.iloc[h + 1:].iterrows():
            get = lambda k: r.iloc[cols[k]] if k in cols else None  # noqa: E731
            name = _text(get("name"))
            if not name or not split_name(name)[0]:
                continue
            p = by_emp.get(_emp(get("emp"))) or by_key.get(name_key(name))
            if p is None:
                close = [q["name"] for q in out.people if _similar(name_key(name), name_key(q["source_name"]))]
                out.warnings.append(
                    f"'{name}' is on the '{sname.strip()}' sheet but not the main sheet — not imported"
                    + (f" (did you mean {', '.join(close)}?)" if close else "") + "."
                )
                continue
            summer = _num(get("summer"))
            if summer is not None:
                p["summer"] = summer
            projected = _text(get("projected")).lower().startswith("y")
            p["likelihood"] = _likelihood(get("likelihood")) or ("Met before summer" if projected else "")
            p["subject"] = _text(get("subject"))

    # people who look like the same person under two spellings
    keys = [(p["name"], name_key(p["source_name"])) for p in out.people]
    for i, (a, ka) in enumerate(keys):
        for b, kb in keys[i + 1:]:
            if _similar(ka, kb):
                out.warnings.append(f"'{a}' and '{b}' may be the same person — both imported; check and "
                                    "remove one if so.")
    return out


# --------------------------------------------------------------------------
# applying it
# --------------------------------------------------------------------------


def _fmt(v: float | None) -> str:
    if v is None:
        return ""
    return str(int(v)) if float(v).is_integer() else str(round(float(v), 2))


@dataclass
class Changes:
    new_staff: list[dict] = field(default_factory=list)
    staff_updates: dict[str, dict] = field(default_factory=dict)   # ID -> {col: value}
    new_plans: list[dict] = field(default_factory=list)
    plan_updates: dict[str, dict] = field(default_factory=dict)


def plan_changes(parsed: Parsed, staff: pd.DataFrame, plans: pd.DataFrame, year: str) -> Changes:
    """What importing `parsed` into `year` ("2026") would change. Existing staff
    are matched by Employee No, then by name; they keep their role, FTE and
    supervisor. Year plan fields the spreadsheet owns are refreshed."""
    ch = Changes()
    st_by_emp = {_emp(e): i for i, e in zip(staff["ID"], staff["Employee No"]) if _emp(e)}
    st_by_key = {name_key(n): i for i, n in zip(staff["ID"], staff["Staff"]) if n}
    st_name = dict(zip(staff["ID"], staff["Staff"]))
    st_rows = staff.set_index("ID")
    yr_plans = plans[plans["Year"].astype(str).str.strip() == year]
    plan_by_name = {n: i for i, n in zip(yr_plans["ID"], yr_plans["Staff"])}
    pl_rows = plans.set_index("ID")

    for p in parsed.people:
        sid = st_by_emp.get(p["emp"]) or st_by_key.get(name_key(p["source_name"]))
        if sid is None:
            row = {"ID": wstore.new_id(), "Staff": p["name"], "Employee No": p["emp"], "Role": cfg.DEFAULT_ROLE,
                   "FTE": "1", "Home discipline": p["unit"], "Active": "FALSE" if p["inactive"] else "TRUE"}
            ch.new_staff.append(row)
            name = p["name"]
        else:
            name = st_name[sid]
            cur = st_rows.loc[sid]
            upd = {}
            if p["emp"] and not str(cur["Employee No"]).strip():
                upd["Employee No"] = p["emp"]
            if p["unit"] and not str(cur["Home discipline"]).strip():
                upd["Home discipline"] = p["unit"]
            if p["inactive"] and str(cur["Active"]).upper() != "FALSE":
                upd["Active"] = "FALSE"
            if upd:
                ch.staff_updates[sid] = upd

        values = {
            "Target (h)": _fmt(p["required"]),
            "Other allocated (h)": _fmt(p["allocated"]),
            "Plan": p["plan"],
            "Summer hrs needed": _fmt(p["summer"]),
            "Likelihood": p["likelihood"],
            "Subject": p["subject"],
            "Notes": p["details"],
        }
        if not any(values.values()):
            continue
        pid = plan_by_name.get(name)
        if pid is None:
            ch.new_plans.append({"ID": wstore.new_id(), "Staff": name, "Year": year, **values})
        else:
            cur = pl_rows.loc[pid]
            upd = {k: v for k, v in values.items() if str(cur[k]) != v}
            if upd:
                ch.plan_updates[pid] = upd
    return ch
