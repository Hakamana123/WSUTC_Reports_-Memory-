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
    base = {"Session": S, "Block": "All", "Weeks": "", "Acting role": "", "DI relief hrs/wk": "", "Notes": ""}
    return pd.DataFrame([{"ID": wstore.new_id(), **base, **r} for r in rows]).reindex(
        columns=ADJUSTMENTS.all_columns, fill_value="")


def cal(*rows, weeks="3", start=None) -> pd.DataFrame:
    """A calendar; default: the 12 blocks of 26, 3 weeks each (36 weeks)."""
    if not rows:
        rows = [{"Session": f"26 {s}", "Block": b} for s in cfg.SESSIONS for b in cfg.BLOCKS]
    base = {"Start date": start or "", "Teaching weeks": weeks, "Notes": ""}
    return pd.DataFrame([{"ID": wstore.new_id(), **base, **r} for r in rows]).reindex(
        columns=wstore.CALENDAR.all_columns, fill_value="")


EARLY = pd.Timestamp("2026-01-01")


def person(name, st_, al, ad=None, calendar=None, as_at=EARLY) -> dict:
    ad = adj().iloc[0:0] if ad is None else ad
    calendar = cal() if calendar is None else calendar
    rec = st_[st_["Staff"] == name].iloc[0].to_dict()
    return rules.person_year(rec, al, ad, rules.calendar_blocks(calendar, "26"), as_at)


def full_year(name, hrs, **kw) -> pd.DataFrame:
    """The same DI hrs/wk in every block of every session of 26."""
    return alloc(*[{"Staff": name, "Session": f"26 {s}", "DI hrs/wk": str(hrs), **kw} for s in cfg.SESSIONS])


# --------------------------------------------------------------------------
# roles and targets
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role, fte, limit",
    [
        ("Teacher (Ongoing)", 1, 16), ("Teacher (Ongoing)", 0.5, 8),
        ("Subject Coordinator", 1, 10), ("Program Coordinator", 1, 6),
        ("Program Coordinator", 0.5, 3), ("Associate Director", 1, 0),
    ],
)
def test_role_hours_pro_rata(role, fte, limit):
    assert rules.role_limit(role, fte) == pytest.approx(limit)


def test_full_time_teacher_target_is_576():
    assert rules.annual_target("Teacher (Ongoing)", 1) == 576
    assert rules.annual_target("Teacher (Ongoing)", 0.5) == 288


def test_college_roles():
    assert set(cfg.STAFF_ROLES) == {
        "Associate Director", "Program Coordinator", "Subject Coordinator",
        "Teacher (Ongoing)", "Teacher (Casual)",
    }
    assert cfg.ACTING_ROLES[0] == cfg.NOT_ACTING


def test_casual_has_no_target():
    st_ = staff({"Staff": "Cas", "Role": "Teacher (Casual)"})
    p = person("Cas", st_, full_year("Cas", 30))
    assert p["Status"] == rules.STATUS_CASUAL and p["Target"] is None and p["Left"] is None
    assert p["Total"] == 30 * 36


# --------------------------------------------------------------------------
# the year: teaching, status, to date
# --------------------------------------------------------------------------


def test_sixteen_hours_all_year_is_on_track():
    st_ = staff({"Staff": "Ana"})
    p = person("Ana", st_, full_year("Ana", 16))
    assert p["Teaching"] == 576 and p["Total"] == 576 and p["Variance"] == 0
    assert p["Avg hrs/wk"] == 16
    assert p["Status"] == rules.STATUS_ON
    assert p["AUT"] == p["SPR"] == p["SUM"] == 192


def test_over_and_under_outside_five_percent():
    st_ = staff({"Staff": "Ana"})
    assert person("Ana", st_, full_year("Ana", 16.5))["Status"] == rules.STATUS_ON    # +3 %
    assert person("Ana", st_, full_year("Ana", 17))["Status"] == rules.STATUS_OVER    # +6 %
    assert person("Ana", st_, full_year("Ana", 15))["Status"] == rules.STATUS_UNDER   # −6 %


def test_block_line_counts_only_in_its_block_and_uses_calendar_weeks():
    st_ = staff({"Staff": "Ana"})
    c = cal({"Session": "26 AUT", "Block": "1", "Teaching weeks": "5"},
            {"Session": "26 AUT", "Block": "2", "Teaching weeks": "4"})
    al = alloc({"Staff": "Ana", "DI hrs/wk": "10"},                  # All → both blocks
               {"Staff": "Ana", "Block": "2", "DI hrs/wk": "2"})
    p = person("Ana", st_, al, calendar=c)
    assert p["Teaching"] == 10 * 9 + 2 * 4
    assert p["Avg hrs/wk"] == pytest.approx(98 / 9)


def test_blocks_missing_from_the_calendar_count_zero_and_are_reported():
    st_ = staff({"Staff": "Ana"})
    c = cal({"Session": "26 AUT", "Block": "1"})
    al = alloc({"Staff": "Ana", "DI hrs/wk": "10"})
    assert person("Ana", st_, al, calendar=c)["Teaching"] == 30
    assert rules.calendar_gaps(al, adj().iloc[0:0], c, "26") == ["26 AUT B2", "26 AUT B3", "26 AUT B4"]


def test_multi_discipline_is_one_person_broken_down():
    st_ = staff({"Staff": "Ana"})
    al = alloc(
        {"Staff": "Ana", "Discipline": "Mathematics", "DI hrs/wk": "8"},
        {"Staff": "Ana", "Discipline": "Science", "DI hrs/wk": "6"},
        {"Staff": "Ana", "Discipline": "Arts", "Block": "2", "DI hrs/wk": "4"},
    )
    p = person("Ana", st_, al)
    assert p["by_discipline"] == {"Mathematics": 8 * 12, "Science": 6 * 12, "Arts": 4 * 3}
    assert p["Teaching"] == 96 + 72 + 12
    assert p["Disciplines"].startswith("Mathematics 96h")
    out = rules.summarise_year(st_, al, adj().iloc[0:0], cal(), "26", EARLY)
    assert list(out["Staff"]) == ["Ana"]


def test_other_years_and_people_are_ignored():
    st_ = staff({"Staff": "Ana"}, {"Staff": "Bo"})
    al = alloc({"Staff": "Ana", "DI hrs/wk": "10"},
               {"Staff": "Ana", "Session": "27 AUT", "DI hrs/wk": "10"},
               {"Staff": "Bo", "DI hrs/wk": "10"})
    assert person("Ana", st_, al)["Teaching"] == 120


def test_to_date_and_left():
    st_ = staff({"Staff": "Ana"})
    c = cal({"Session": "26 AUT", "Block": "1", "Start date": "2026-03-02"},
            {"Session": "26 AUT", "Block": "2", "Start date": "2026-03-30"})
    al = alloc({"Staff": "Ana", "DI hrs/wk": "16"})
    # two full weeks of block 1 done by Sunday 15 March
    p = person("Ana", st_, al, calendar=c, as_at=pd.Timestamp("2026-03-15"))
    assert p["To date"] == pytest.approx(32)
    assert p["Left"] == pytest.approx(576 - 32)
    # all of block 1, none of block 2, by 29 March
    assert person("Ana", st_, al, calendar=c, as_at=pd.Timestamp("2026-03-29"))["To date"] == pytest.approx(48)
    assert person("Ana", st_, al, calendar=c, as_at=pd.Timestamp("2027-01-01"))["To date"] == pytest.approx(96)


def test_elapsed_weeks_is_clamped():
    start = pd.Timestamp("2026-03-02")
    assert rules.elapsed_weeks(start, 3, pd.Timestamp("2026-03-01")) == 0
    assert rules.elapsed_weeks(start, 3, pd.Timestamp("2026-03-08")) == 1
    assert rules.elapsed_weeks(start, 3, pd.Timestamp("2026-12-01")) == 3
    assert rules.elapsed_weeks(None, 3, pd.Timestamp("2026-12-01")) == 0


# --------------------------------------------------------------------------
# higher duties and other duties
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role, acting, hda",
    [("Teacher (Ongoing)", "Subject Coordinator", 6),
     ("Subject Coordinator", "Program Coordinator", 4),
     ("Program Coordinator", "Associate Director", 6),
     ("Teacher (Ongoing)", "Program Coordinator", 10)],
)
def test_acting_turns_untaught_di_hours_into_hda(role, acting, hda):
    row = {"Type": cfg.HIGHER_DUTIES, "Acting role": acting, "DI relief hrs/wk": ""}
    assert rules.duty_hours_per_week(row, role, 1) == hda
    assert rules.duty_hours_per_week(row, role, 0.5) == hda / 2


def test_teacher_acting_as_subject_coordinator_all_year_stays_on_track():
    st_ = staff({"Staff": "Ana"})
    ad = adj(*[{"Staff": "Ana", "Session": f"26 {s}", "Type": cfg.HIGHER_DUTIES,
                "Acting role": "Subject Coordinator"} for s in cfg.SESSIONS])
    p = person("Ana", st_, full_year("Ana", 10), ad)
    assert p["Teaching"] == 360 and p["Duties"] == 216 and p["Total"] == 576
    assert p["Status"] == rules.STATUS_ON
    assert p["Acting"] == "Subject Coordinator"
    assert "Acting Subject Coordinator (26 AUT)" in p["Adjustments"]


def test_na_acting_role_uses_the_hours_entered_for_part_of_a_block():
    st_ = staff({"Staff": "Ana"})
    ad = adj({"Staff": "Ana", "Type": cfg.HIGHER_DUTIES, "Acting role": cfg.NOT_ACTING,
              "DI relief hrs/wk": "4", "Block": "1", "Weeks": "2"},
             {"Staff": "Ana", "Type": "Curriculum development relief", "DI relief hrs/wk": "2",
              "Block": "2", "Weeks": "10"})                          # capped at the block's 3
    p = person("Ana", st_, alloc({"Staff": "Ana", "DI hrs/wk": "0"}), ad)
    assert p["Duties"] == 4 * 2 + 2 * 3
    assert "2 wk" in p["Adjustments"] and p["Acting"] == ""


def test_part_block_duties_to_date_count_from_the_block_start():
    st_ = staff({"Staff": "Ana"})
    c = cal({"Session": "26 AUT", "Block": "1", "Start date": "2026-03-02"})
    ad = adj({"Staff": "Ana", "Type": "Other approved release", "DI relief hrs/wk": "5", "Weeks": "1"})
    p = person("Ana", st_, alloc({"Staff": "Ana", "DI hrs/wk": "0"}), ad, calendar=c,
               as_at=pd.Timestamp("2026-03-15"))
    assert p["Duties"] == 5 and p["To date"] == 5


# --------------------------------------------------------------------------
# summary / helpers
# --------------------------------------------------------------------------


def test_summarise_skips_inactive_staff():
    st_ = staff({"Staff": "Ana"}, {"Staff": "Gone", "Active": "FALSE"})
    out = rules.summarise_year(st_, alloc({"Staff": "Ana", "DI hrs/wk": "4"}), adj().iloc[0:0],
                               cal(), "26", EARLY)
    assert list(out["Staff"]) == ["Ana"]


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


def test_copy_year_maps_each_session_to_the_same_one_next_year():
    al = alloc({"Staff": "Ana", "DI hrs/wk": "8"}, {"Staff": "Ana", "Session": "26 SPR"},
               {"Staff": "Ana", "Session": "25 SPR"})
    rows = wstore.copy_year(al, "26", "27")
    assert sorted(r["Session"] for r in rows) == ["27 AUT", "27 SPR"]
