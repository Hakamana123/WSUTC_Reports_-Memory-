"""Tests for teaching-load rules (workload_rules) and the tables + change log
(workload_store), against an in-memory fake Backend."""

from __future__ import annotations

import pandas as pd
import pytest

import workload_config as cfg
import workload_rules as rules
import workload_store as wstore
from test_store import FakeBackend
from workload_store import ADJUSTMENTS, ALLOCATIONS, STAFF

S = "26 AUT"


def staff(*rows) -> pd.DataFrame:
    base = {"Role": "Teacher (Ongoing)", "FTE": "1", "Supervisor": "Pat", "Home discipline": "",
            "Active": "TRUE", "Notes": ""}
    return pd.DataFrame([{"ID": wstore.new_id(), **base, **r} for r in rows]).reindex(
        columns=STAFF.all_columns, fill_value="")


def alloc(*rows) -> pd.DataFrame:
    base = {"Session": S, "Block": "All", "Discipline": "Mathematics", "Subject": "",
            "Classes": "1", "Notes": ""}
    return pd.DataFrame([{"ID": wstore.new_id(), **base, **r} for r in rows]).reindex(
        columns=ALLOCATIONS.all_columns, fill_value="")


def adj(*rows) -> pd.DataFrame:
    base = {"Session": S, "Block": "All", "Acting role": "", "DI relief hrs/wk": "", "Notes": ""}
    return pd.DataFrame([{"ID": wstore.new_id(), **base, **r} for r in rows]).reindex(
        columns=ADJUSTMENTS.all_columns, fill_value="")


def person(name, st_, al, ad=None, session=S) -> dict:
    ad = adj().iloc[0:0] if ad is None else ad
    rec = st_[st_["Staff"] == name].iloc[0].to_dict()
    return rules.person_session(rec, al, ad, session)


# --------------------------------------------------------------------------
# limits
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role, fte, limit",
    [
        ("Teacher (Ongoing)", 1, 16), ("Teacher (Ongoing)", 0.5, 8),
        ("Subject Coordinator", 1, 12), ("Program Coordinator", 1, 8),
        ("Program Coordinator", 0.5, 4),
    ],
)
def test_role_limits_come_from_the_ea_schedules_pro_rata(role, fte, limit):
    assert rules.role_limit(role, fte) == pytest.approx(limit)


def test_casual_has_no_limit():
    st_ = staff({"Staff": "Cas", "Role": "Teacher (Casual)"})
    p = person("Cas", st_, alloc({"Staff": "Cas", "DI hrs/wk": "30"}))
    assert p["Status"] == rules.STATUS_CASUAL and p["Limit"] is None
    assert p["Avg load"] == 30


# --------------------------------------------------------------------------
# load and status
# --------------------------------------------------------------------------


def test_all_block_line_counts_in_every_block():
    st_ = staff({"Staff": "Ana"})
    p = person("Ana", st_, alloc({"Staff": "Ana", "DI hrs/wk": "12"}))
    assert [p[f"B{b}"] for b in cfg.BLOCKS] == [12, 12, 12, 12]
    assert p["Avg load"] == 12 and p["Spare"] == 4
    assert p["Status"] == rules.STATUS_SPARE


def test_status_full_over_and_peak():
    st_ = staff({"Staff": "Ana"})
    assert person("Ana", st_, alloc({"Staff": "Ana", "DI hrs/wk": "15.5"}))["Status"] == rules.STATUS_FULL
    assert person("Ana", st_, alloc({"Staff": "Ana", "DI hrs/wk": "17"}))["Status"] == rules.STATUS_OVER

    # 20 h in block 1 only, 12 h in blocks 2-4 → average 14, but block 1 over
    peak = alloc({"Staff": "Ana", "DI hrs/wk": "12"}, {"Staff": "Ana", "Block": "1", "DI hrs/wk": "8"})
    p = person("Ana", st_, peak)
    assert p["Avg load"] == 14
    assert p["Status"] == rules.STATUS_PEAK and p["Over blocks"] == "1"


def test_multi_discipline_load_is_summed_and_broken_down():
    st_ = staff({"Staff": "Ana"})
    al = alloc(
        {"Staff": "Ana", "Discipline": "Mathematics", "DI hrs/wk": "8"},
        {"Staff": "Ana", "Discipline": "Science", "DI hrs/wk": "6"},
        {"Staff": "Ana", "Discipline": "Arts", "Block": "2", "DI hrs/wk": "4"},  # one block → 1 h avg
    )
    p = person("Ana", st_, al)
    assert p["Avg load"] == 15
    assert p["by_discipline"] == {"Mathematics": 8, "Science": 6, "Arts": 1}
    assert p["Disciplines"].startswith("Mathematics 8h")


def test_other_sessions_and_people_are_ignored():
    st_ = staff({"Staff": "Ana"}, {"Staff": "Bo"})
    al = alloc({"Staff": "Ana", "DI hrs/wk": "10"},
               {"Staff": "Ana", "Session": "26 SPR", "DI hrs/wk": "10"},
               {"Staff": "Bo", "DI hrs/wk": "10"})
    assert person("Ana", st_, al)["Avg load"] == 10


# --------------------------------------------------------------------------
# higher duties and relief
# --------------------------------------------------------------------------


def test_higher_duties_replace_the_limit_for_those_blocks():
    st_ = staff({"Staff": "Ana"})
    al = alloc({"Staff": "Ana", "DI hrs/wk": "6"})
    ad = adj({"Staff": "Ana", "Type": cfg.HIGHER_DUTIES, "Acting role": "Program Coordinator",
              "Block": "1"})
    p = person("Ana", st_, al, ad)
    # limit 8 in block 1, 16 in blocks 2-4
    assert p["Limit"] == pytest.approx((8 + 16 * 3) / 4)
    assert p["Acting"] == "Program Coordinator"
    assert p["Status"] == rules.STATUS_SPARE

    # 12 h all session: fine on average (limit 14) but over in the acting block
    p = person("Ana", st_, alloc({"Staff": "Ana", "DI hrs/wk": "12"}), ad)
    assert p["Status"] == rules.STATUS_PEAK and p["Over blocks"] == "1"


def test_acting_as_coordinator_all_session_uses_that_limit():
    st_ = staff({"Staff": "Ana"})
    ad = adj({"Staff": "Ana", "Type": cfg.HIGHER_DUTIES, "Acting role": "Subject Coordinator"})
    p = person("Ana", st_, alloc({"Staff": "Ana", "DI hrs/wk": "14"}), ad)
    assert p["Limit"] == 12 and p["Status"] == rules.STATUS_OVER


def test_only_the_four_college_roles():
    assert set(cfg.STAFF_ROLES) == {
        "Program Coordinator", "Subject Coordinator", "Teacher (Ongoing)", "Teacher (Casual)",
    }


def test_relief_reduces_the_limit_and_scales_with_fte_first():
    st_ = staff({"Staff": "Ana", "FTE": "0.5"})
    ad = adj({"Staff": "Ana", "Type": "Curriculum development relief", "DI relief hrs/wk": "2"},
             {"Staff": "Ana", "Type": "Travel time between campuses", "DI relief hrs/wk": "1"})
    p = person("Ana", st_, alloc({"Staff": "Ana", "DI hrs/wk": "5"}), ad)
    assert p["Limit"] == 5            # 16 × 0.5 − 3
    assert p["Status"] == rules.STATUS_FULL
    assert "−2h" in p["Adjustments"]


def test_relief_never_takes_the_limit_below_zero():
    st_ = staff({"Staff": "Ana", "Role": "Program Coordinator"})
    ad = adj({"Staff": "Ana", "Type": "Other approved release", "DI relief hrs/wk": "10"})
    assert person("Ana", st_, alloc({"Staff": "Ana", "DI hrs/wk": "0"}), ad)["Limit"] == 0


# --------------------------------------------------------------------------
# summary / year / helpers
# --------------------------------------------------------------------------


def test_summarise_skips_inactive_staff():
    st_ = staff({"Staff": "Ana"}, {"Staff": "Gone", "Active": "FALSE"})
    out = rules.summarise(st_, alloc({"Staff": "Ana", "DI hrs/wk": "4"}), adj().iloc[0:0], S)
    assert list(out["Staff"]) == ["Ana"]


def test_year_average_uses_only_sessions_with_teaching():
    st_ = staff({"Staff": "Ana"})
    al = alloc({"Staff": "Ana", "DI hrs/wk": "18"},
               {"Staff": "Ana", "Session": "26 SPR", "DI hrs/wk": "12"})
    load, limit = rules.year_average(st_.iloc[0].to_dict(), al, adj().iloc[0:0], "26")
    assert (load, limit) == (15, 16)   # 18 in AUT is fine once SPR averages it out


def test_orphans_lists_names_not_on_the_staff_list():
    assert rules.orphans(staff({"Staff": "Ana"}), alloc({"Staff": "Ana"}, {"Staff": "Zed"})) == ["Zed"]


@pytest.mark.parametrize(
    "date, expected",
    [("2026-03-10", "26 AUT"), ("2026-09-19", "26 SPR"), ("2026-12-05", "27 SUM"), ("2027-01-10", "27 SUM")],
)
def test_default_session(date, expected):
    assert rules.default_session(pd.Timestamp(date)) == expected


def test_session_sort_order():
    assert sorted(["26 SUM", "27 AUT", "26 AUT", "26 SPR"], key=rules.session_sort_key) == \
        ["26 AUT", "26 SPR", "26 SUM", "27 AUT"]


# --------------------------------------------------------------------------
# store + change log
# --------------------------------------------------------------------------


@pytest.fixture
def b():
    return FakeBackend(), FakeBackend()


def test_add_then_load_round_trips(b):
    tab, log = b
    df = alloc({"Staff": "Ana", "Subject": "MATH1001", "DI hrs/wk": "8"})
    wstore.save(tab, log, ALLOCATIONS, df, set(df["ID"]), set(), by="Josiah")
    loaded = wstore.load(tab, ALLOCATIONS)
    assert loaded.iloc[0]["DI hrs/wk"] == "8" and loaded.iloc[0]["last_saved_by"] == "Josiah"
    entry = wstore.load_log(log).iloc[0]
    assert entry["Change"] == "added" and entry["Row"] == f"Ana · {S} · MATH1001"


def test_edit_logs_each_changed_field(b):
    tab, log = b
    df = alloc({"Staff": "Ana", "DI hrs/wk": "8"})
    wstore.save(tab, log, ALLOCATIONS, df, set(df["ID"]), set(), by="Josiah")

    edited = wstore.load(tab, ALLOCATIONS)
    edited.loc[0, "DI hrs/wk"] = "10"
    edited.loc[0, "Discipline"] = "Science"
    wstore.save(tab, log, ALLOCATIONS, edited, set(edited["ID"]), set(), by="Chris")

    h = wstore.load_log(log)
    e = h[h["Change"] == "edited"].set_index("Field")
    assert set(e.index) == {"DI hrs/wk", "Discipline"}
    assert (e.loc["DI hrs/wk", "From"], e.loc["DI hrs/wk", "To"]) == ("8", "10")


def test_unchanged_save_writes_no_log(b):
    tab, log = b
    df = staff({"Staff": "Ana"})
    wstore.save(tab, log, STAFF, df, set(df["ID"]), set(), by="J")
    wstore.save(tab, log, STAFF, wstore.load(tab, STAFF), set(df["ID"]), set(), by="J")
    assert len(wstore.load_log(log)) == 1


def test_concurrent_saves_to_different_rows_both_survive(b):
    tab, log = b
    df = alloc({"Staff": "Ana"}, {"Staff": "Bo"})
    wstore.save(tab, log, ALLOCATIONS, df, set(df["ID"]), set(), by="J")
    stale = wstore.load(tab, ALLOCATIONS)
    a_id, b_id = stale["ID"]

    theirs = stale.copy(); theirs.loc[1, "Notes"] = "by Chris"
    wstore.save(tab, log, ALLOCATIONS, theirs, {b_id}, set(), by="Chris")
    ours = stale.copy(); ours.loc[0, "Notes"] = "by Josiah"
    after = wstore.save(tab, log, ALLOCATIONS, ours, {a_id}, set(), by="Josiah").set_index("ID")

    assert after.loc[a_id, "Notes"] == "by Josiah"
    assert after.loc[b_id, "Notes"] == "by Chris"


def test_remove_keeps_contents_in_the_log(b):
    tab, log = b
    df = alloc({"Staff": "Ana", "Subject": "MATH1001", "DI hrs/wk": "8"})
    wstore.save(tab, log, ALLOCATIONS, df, set(df["ID"]), set(), by="J")
    wstore.save(tab, log, ALLOCATIONS, df, set(), set(df["ID"]), by="Nat")
    assert wstore.load(tab, ALLOCATIONS).empty
    last = wstore.load_log(log).iloc[0]
    assert last["Change"] == "removed" and "DI hrs/wk=8" in last["From"]


def test_copy_session_gives_new_ids_and_target_session():
    al = alloc({"Staff": "Ana", "DI hrs/wk": "8"}, {"Staff": "Bo", "DI hrs/wk": "6"},
               {"Staff": "Ana", "Session": "26 SPR"})
    rows = wstore.copy_session(al, S, "27 AUT", staff={"Ana"})
    assert len(rows) == 1
    assert rows[0]["Session"] == "27 AUT" and rows[0]["DI hrs/wk"] == "8"
    assert rows[0]["ID"] not in set(al["ID"])
