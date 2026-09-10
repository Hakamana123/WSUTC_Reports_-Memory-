# Glossary

The controlled vocabulary for the IA Mapping tool. Source of record for
reviewers. Based on Koh & Roffey, *Assessment-Mapping Tool: Proposed
Relabelling on Inspire × Assure Axes* (5 Sep 2026).

There are four separate vocabularies. They are easy to run together, so:

- **Bands** are the two ratings a reviewer *sets*.
- **Quadrant** and **Action tier** are *derived* from those bands — nobody
  sets them directly.
- **Planning fields** are what a reviewer adds on top for redesign planning.

---

## A. Bands — what a reviewer sets

Two independent axes, four levels each. This is the only judgement call; every
other controlled value is derived from these two.

### Assure axis

How securely the task evidences the Subject Learning Outcomes (SLOs).
Wording is **verbatim WSU / IA language** and must not be paraphrased.

| Band | Meaning |
|---|---|
| **Assured** | Provides sufficient evidence to assure achievement of the SLOs. The task is both secure and supervised. |
| **Contributes to Assurance** | Provides useful evidence or contributes to the assurance picture for a subject overall but does not independently provide sufficient assurance. Could also assure student learning in progress as a checkpoint but misses some SLOs covered in later assessments. |
| **Potential Assurance** | Has the potential to provide assurance but would require changes to the task, assessment conditions or evidence collected. |
| **Not Assured** | Does not currently contribute meaningful evidence for assurance of the learning outcome. |

### Inspire axis

How strongly the task motivates learning. Judged on **FIRE** — Formative,
Instant feedback, Repeatable, Evaluative judgement.

| Band | Meaning |
|---|---|
| **Inspiring** | Strongly motivates learning and exhibits the FIRE qualities: formative and part of the learning process, gives students timely feedback they can act on, allows practice or iteration, and develops their evaluative judgement. Authentic and meaningful to students. |
| **Contributes to Inspiration** | Motivates learning in part and reflects some FIRE qualities but not others (e.g. a single attempt with little iteration, or weak development of evaluative judgement). Supports engagement but is not the main driver of learning. |
| **Potential to Inspire** | Has the capacity to motivate learning but would require changes to the task, its framing, or its feedback and iteration design to realise the FIRE qualities. |
| **Not Inspiring** | Does not currently motivate meaningful engagement or learning; exhibits few or none of the FIRE qualities. |

### Band ordinal

Internally each band is a 1–4 number (Not = 1 … top = 4). Used for the
high/low rollup and the action tier. Reviewers never see the number.

---

## B. Derived — nobody sets these

### Quadrant

Each band collapses to **high** (band ≥ 3: *Assured*/*Contributes*, or
*Inspiring*/*Contributes*) or **low** (band ≤ 2). Crossed:

| | High Assure | Low Assure |
|---|---|---|
| **High Inspire** | High Inspire · High Assure | High Inspire · Low Assure |
| **Low Inspire** | Low Inspire · High Assure | Low Inspire · Low Assure |

| Quadrant | What it means | What to consider |
|---|---|---|
| **High Inspire · High Assure** | Motivates learning and provides secure evidence | Retain; use as an exemplar; protect from drift over time |
| **High Inspire · Low Assure** | Engages students but the evidence isn't secure | Keep the task; add a secured checkpoint or verification layer rather than discard it |
| **Low Inspire · High Assure** | Secure evidence but limited learning value | Reconsider purpose; can it be made more authentic/engaging without losing security? |
| **Low Inspire · Low Assure** | Neither motivates nor secures | Redesign substantially or retire |

The old single-label scheme — "Inspire" / "Assure" / "Inspire & Assure" /
"Low value" — is **retired**. The tool never produces it. The round-1 label is
shown beside the new quadrant only as reference / migration check.

### Action tier

Redesign priority, driven by the **weaker of the two bands**.

| Weaker band | Tier | Priority | Meaning |
|---|---|---|---|
| Assured / Inspiring (4) | **Retain** | — | No action required. |
| Contributes (3) | **Enhance** | low | Working, but could be strengthened. |
| Potential (2) | **Targeted redesign** | medium | A defined, bounded change. |
| Not Assured / Not Inspiring (1) | **Full redesign** | high | Substantial rework, or retire. |

The tier says *how urgent*; the pair of bands says *what kind of fix*. A task
that is Not Assured but Inspiring keeps its engaging design and gains a secured
checkpoint; a task that is Assured but Not Inspiring is secure but low value
and is reworked for engagement. Same tier, different fix.

### Position (sequence)

Where the task sits in its subject's assessment sequence. Used only by the
optional position weighting.

| Position | Rule |
|---|---|
| **early** | first task, and the subject has ≥ 2 tasks |
| **final** | last task, and the subject has ≥ 2 tasks |
| **mid** | anywhere between first and last |
| **single** | the subject has one task, or the number is missing |

### Position weighting (optional, toggle — default on)

**Not part of the endorsed proposal** — a tool extension. When on, it softens
the suggested action tier in exactly two situations, and never the reverse:

- **early** task, Assure is the weaker axis and sits at Potential/Not →
  Assure is treated as one band stronger.
  *"Early task — low assurance is acceptable at a formative / checkpoint stage."*
- **final** task, Inspire is the weaker axis and sits at Potential/Not →
  Inspire is treated as one band stronger.
  *"Final task — inspiration isn't the priority here; assurance is."*

Inspiration is never softened early; assurance is never softened at the final;
`mid` and `single` are never softened. The tool always shows both the
axis-only tier and the position-aware tier, so you can see when position
changed the recommendation.

---

## C. Planning fields — the reviewer adds these

Not derived. Free text unless noted.

| Field | Type | For |
|---|---|---|
| **Action** | picklist — the 4 tiers | Defaults to the suggested tier; the reviewer can override. |
| **Effort** | Low / Medium / High | Shown when the task isn't "Retain". Feeds an effort-vs-impact view across a program. |
| **Quick wins** | free text | Small fixes that don't need a redesign — regardless of the task's tier. |
| **Resource requirements / considerations** | free text | What a redesign would need: staff time, software, room type, etc. |
| **Rationale / Notes** | free text | Why the bands are what they are. |

---

## D. Confirmation

| Flag | Meaning |
|---|---|
| **Confirmed_R1** | The export's original `Confirmed` column — round-1 history. Read-only in this tool. |
| **Confirmed_R2** | This round's sign-off. Starts unchecked. A row's bands are only treated as authoritative — and are never re-scored from the round-1 number — once this is ticked. |

---

## E. Row identity

**RowKey** = `Source File :: Assessment Number`. Stable across re-imports and
unique even where a subject code appears twice in the export (a single-program
version and an all-programs version).
