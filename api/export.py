"""PDF and Excel export for one completed run.

Pure formatting over an already-fetched RunDetail -- no tradingagents import
needed here, same shape as api/push.py. Both builders take the SAME
RunDetail and return in-memory bytes; the router writes those bytes
straight into the response, no temp file, nothing to clean up.
"""

from __future__ import annotations

import io
import re

from fpdf import FPDF
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from api.schemas import RunDetail

# (group label, [(Reports field, display label), ...]) -- same grouping and
# order as ReportsRecord.tsx's GROUPS, so the export reads the same as the
# page it was exported from: conclusion first (Portfolio, Trader), then the
# arguments (Research, Risk panel), then the raw inputs (Analysts) last.
REPORT_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Portfolio", [("final_decision", "Final decision")]),
    ("Trader", [("trader_plan", "Trader plan")]),
    ("Research", [
        ("investment_plan", "Investment plan"),
        ("bull_case", "Bull case"),
        ("bear_case", "Bear case"),
    ]),
    ("Risk panel", [("risk_debate", "Risk debate")]),
    ("Analysts", [
        ("market", "Market"),
        ("sentiment", "Sentiment"),
        ("news", "News"),
        ("fundamentals", "Fundamentals"),
    ]),
]

# fpdf2's core fonts (Helvetica) are Latin-1 only and raise
# FPDFUnicodeEncodingException on any character outside that range --
# verified live, twice: a bare rupee sign crashes cell()/multi_cell()
# outright (not a rendering glitch), and so does a plain em-dash in a
# header string this module wrote itself. Report text is full of currency
# figures, and both report prose and this file's own labels use "smart"
# punctuation freely, so every string that reaches fpdf2 goes through this
# first -- not just the ones known in advance to contain a rupee sign.
# Embedding a Unicode TTF font would avoid the substitution entirely, but
# adds a binary asset and a font-license question this project doesn't need
# to take on for a currency symbol and some punctuation.
_PDF_UNSAFE_CHARS = {
    "₹": "Rs. ",
    "—": "-",  # em dash
    "–": "-",  # en dash
    "‘": "'", "’": "'",  # curly single quotes
    "“": '"', "”": '"',  # curly double quotes
    "…": "...",
    "→": "->", "←": "<-",  # arrows -- found live in a real run's report text
    "•": "-",
}


def _pdf_safe(text: str) -> str:
    for unsafe, safe in _PDF_UNSAFE_CHARS.items():
        text = text.replace(unsafe, safe)
    # Catch-all, not just the finite table above: LLM-authored report text
    # can contain any Unicode character (checkmarks, other currency signs,
    # non-Latin scripts), and each one this table doesn't happen to know
    # about crashes the WHOLE export rather than rendering oddly --
    # confirmed live against a real run whose report used "→", which broke
    # export even after the rupee/dash/quote substitutions above already
    # shipped. A denylist can never be complete; this makes completeness
    # unnecessary by falling back to "?" for anything still outside Latin-1.
    return "".join(ch if ord(ch) < 256 else "?" for ch in text)


def _money(value: float | None, symbol: str) -> str:
    if value is None:
        return "Not set"
    return f"{symbol}{value:,.2f}"


def _verdict_rows(run: RunDetail, symbol: str) -> list[tuple[str, str]]:
    """The same six fields TheCall.tsx's stat grid shows, in the same
    order, so the export matches what a reader already saw on screen."""
    verdict = run.verdict
    levels = verdict.levels if verdict else None
    return [
        ("Current price", _money(verdict.current_price if verdict else None, symbol)),
        ("Action", (levels.action if levels else None) or "Not set"),
        ("Entry", _money(levels.entry_price if levels else None, symbol)),
        ("Stop", _money(levels.stop_loss if levels else None, symbol)),
        ("Exit", _money(verdict.price_target if verdict else None, symbol)),
        ("Horizon", (verdict.time_horizon if verdict else None) or "Not set"),
    ]


def _available_reports(run: RunDetail) -> list[tuple[str, str, str]]:
    """Flattened (group, label, content) for every report field the run
    actually has -- a run with analysts deselected has fewer than 10."""
    if run.reports is None:
        return []
    out = []
    for group_label, fields in REPORT_GROUPS:
        for key, label in fields:
            content = getattr(run.reports, key)
            if content:
                out.append((group_label, label, content))
    return out


def build_pdf(run: RunDetail) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, _pdf_safe(run.ticker), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(103, 109, 128)  # #676D80, the app's own meta-text grey
    profile_label = "Detailed" if run.profile.value == "detailed" else "Fast"
    pdf.cell(0, 8, f"{run.analysis_date}  -  {profile_label} analysis", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    rating = (run.verdict.rating if run.verdict else None) or "Not set"
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 10, _pdf_safe(f"Rating: {rating}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 11)
    for label, value in _verdict_rows(run, symbol="Rs. "):
        pdf.cell(38, 7, _pdf_safe(label), new_x="RIGHT", new_y="TOP")
        pdf.cell(0, 7, _pdf_safe(value), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    for group_label, label, content in _available_reports(run):
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(28, 111, 230)  # --accent-1, matching the app's section accent
        pdf.cell(0, 9, _pdf_safe(f"{group_label} - {label}"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 10)
        # markdown=True: fpdf2's own minimal **bold**/__underline__ support,
        # so the report's existing "**Rating**: Buy" style labels render as
        # actual bold instead of literal asterisks -- no custom parser needed.
        pdf.multi_cell(0, 5.5, _pdf_safe(content), markdown=True)
        pdf.ln(4)

    return bytes(pdf.output())


def build_excel(run: RunDetail) -> bytes:
    wb = Workbook()
    summary_ws = wb.active
    summary_ws.title = "Summary"

    header_rows = [
        ("Ticker", run.ticker),
        ("Analysis date", str(run.analysis_date)),
        ("Profile", run.profile.value.capitalize()),
        ("Status", run.status.value.capitalize()),
        ("Rating", (run.verdict.rating if run.verdict else None) or "Not set"),
    ]
    rows = header_rows + _verdict_rows(run, symbol="₹")  # Excel handles Unicode natively
    for i, (label, value) in enumerate(rows, start=1):
        summary_ws.cell(row=i, column=1, value=label).font = Font(bold=True)
        summary_ws.cell(row=i, column=2, value=value)
    summary_ws.column_dimensions["A"].width = 18
    summary_ws.column_dimensions["B"].width = 44

    reports_ws = wb.create_sheet("Full reports")
    header = ("Group", "Report", "Word count", "Content")
    reports_ws.append(header)
    for cell in reports_ws[1]:
        cell.font = Font(bold=True)

    for group_label, label, content in _available_reports(run):
        word_count = len(re.findall(r"\S+", content))
        reports_ws.append([group_label, label, word_count, content])

    widths = {"A": 14, "B": 18, "C": 12, "D": 110}
    for column_letter, width in widths.items():
        reports_ws.column_dimensions[column_letter].width = width
    for row in reports_ws.iter_rows(min_row=2, min_col=4, max_col=4):
        row[0].alignment = Alignment(wrap_text=True, vertical="top")

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
