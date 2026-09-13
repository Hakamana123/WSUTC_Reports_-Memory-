# IA Mapping

A small Streamlit tool for reviewing WSU assessment tasks on the **Inspire**
and **Assure** axes. It takes the assessment-mapping export, adds the round-2
layer — four-level bands, a derived quadrant, a sequence-aware redesign action
— and lets a small review team override, confirm, and export.

Based on *Assessment-Mapping Tool: Proposed Relabelling on Inspire × Assure
Axes* (Koh & Roffey, Sept 2026).

## Status

| Part | State |
|---|---|
| `config.py` — contestable values | done |
| `derivation.py` — pure banding / quadrant / position / action logic | done |
| `loader.py` — read + clean the export | done |
| `store.py` — Google Sheet as shared store | done, live-verified |
| `pages/1_IA_Mapping.py` — Streamlit review table | done, live-verified |
| `pages/2_Workload_Management.py` | not yet scoped |

77 tests passing. Google Sheet setup: see `SETUP_GOOGLE_SHEET.md`, then
`python scripts/smoke_test_sheet.py`.

This is a **multipage app** (Streamlit's native `pages/` convention, same as
WSTUCReports) — `app.py` is just the landing page. Run it with:

```
streamlit run app.py
```

Not yet deployed to Streamlit Community Cloud, and no GitHub remote yet —
separate step, unrelated to WSTUCReports' own repo/hosting.

Run the tests:

```
pip install pytest
python -m pytest
```

## How the derivation works

1. **Bands.** Each round-1 score (1–10) becomes one of four levels using cut
   points `(low, mid, high)`, default `(4, 6, 8)`: `>= high → 4`, `>= mid → 3`,
   `>= low → 2`, else `1`. A human-set band always wins over the score (and a
   confirmed row's band is never recomputed).
2. **Quadrant.** Each axis collapses to high (band ≥ 3) / low, crossed into one
   of: `High Inspire · High Assure`, `High Inspire · Low Assure`,
   `Low Inspire · High Assure`, `Low Inspire · Low Assure`. The retired
   single-label scheme ("Low value" etc.) is never produced.
3. **Position.** Per subject, from the assessment number and the subject's max:
   first of ≥2 → `early`, last of ≥2 → `final`, between → `mid`, otherwise
   `single`.
4. **Action.** Base tier from the weaker axis band: 4 → Retain, 3 → Enhance,
   2 → Targeted redesign, 1 → Full redesign. If position weighting is on
   (default, **not** part of the endorsed proposal), a weak Assure at an
   `early` task or a weak Inspire at a `final` task is treated as one band
   stronger — and only those two directions, never the reverse.

Everything contestable is in `config.py`.

## Deployment (planned)

- Streamlit Community Cloud, viewing restricted to an email allowlist.
- State lives in one Google Sheet (a GCP service account; its key in
  `.streamlit/secrets.toml`, which is git-ignored). The Sheet is the system of
  record; Streamlit Cloud's own disk is treated as disposable.
- No WSU IT dependency. No LLM. No live SharePoint in v1 — the export seeds the
  Sheet once and a manual re-import carries results back.

### Later: live SharePoint (v2)

Reading/writing the ProgramCoordinators list directly needs a Microsoft Graph
app registration from WSU IT (`Sites.Selected`, granted on that one site). Out
of scope for v1.
