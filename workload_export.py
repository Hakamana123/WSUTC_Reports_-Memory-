"""The dashboard's year grid as an Excel workbook: Name / Role / Program, then
a subjects column and an hours column (the block's total) per block in
calendar order, then target, total, ± and status. Hours are tinted as on
screen — blue by how full the block is, orange over the limit, grey for
casuals — and the current block's header is green. Names and the header row
are frozen. Pure: a DataFrame in, bytes out.
"""

from __future__ import annotations

from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ORANGE = PatternFill("solid", fgColor="F8C9A0")
GREY = PatternFill("solid", fgColor="EBEBEB")
GREEN = PatternFill("solid", fgColor="D5EFD9")
HEADER = PatternFill("solid", fgColor="EDEDED")

TITLES = {"Staff": "Name", "Target": "Target (h)", "Total": "Total (h)", "Variance": "± Target (h)"}


def _value(v):
    """Numbers shown as text on screen ("16", "1,024", "+12") back to numbers."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, str):
        try:
            return float(v.replace(",", "")) if v.strip() else None
        except ValueError:
            return v
    return v


def _blue(load: float) -> PatternFill:
    """White → the dashboard's blue (76, 120, 168) as the block fills up."""
    a = 0.06 + 0.34 * min(max(load, 0.0), 1.0)
    rgb = "".join(f"{round(255 - (255 - c) * a):02X}" for c in (76, 120, 168))
    return PatternFill("solid", fgColor=rgb)


def _fill(load: float | None) -> PatternFill:
    if load is None:
        return GREY
    return ORANGE if load > 1 + 1e-9 else _blue(load)


def grid_xlsx(grid: pd.DataFrame, labels: list[str], load: dict[tuple[str, str], float | None],
              now: str | None, sheet: str = "Workload") -> bytes:
    """`grid` from workload_rules.year_grid joined with Target, Total,
    Variance and Status; `load` as year_grid returns it."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet[:31]
    cols = list(grid.columns)
    hours = {f"{lb} h": lb for lb in labels}

    for j, c in enumerate(cols, 1):
        title = "Hours" if c in hours else TITLES.get(c, c)
        if c == now:
            title += " (now)"
        cell = ws.cell(row=1, column=j, value=title)
        current = c == now or hours.get(c) == now
        cell.font, cell.fill = Font(bold=True), GREEN if now and current else HEADER
        cell.alignment = Alignment(horizontal="center")

    for i, row in enumerate(grid.itertuples(index=False), 2):
        name = row[0]
        for j, (c, v) in enumerate(zip(cols, row), 1):
            cell = ws.cell(row=i, column=j, value=_value(v))
            if c in hours and (name, hours[c]) in load:
                cell.fill = _fill(load[(name, hours[c])])
                cell.number_format = "#,##0"
                if cell.fill is ORANGE:
                    cell.font = Font(bold=True)

    for j, c in enumerate(cols, 1):
        width = 7 if c in hours else 28 if c in labels or c in ("Staff", "Program") else 14
        ws.column_dimensions[get_column_letter(j)].width = width
    ws.freeze_panes = "D2"

    out = BytesIO()
    wb.save(out)
    return out.getvalue()
