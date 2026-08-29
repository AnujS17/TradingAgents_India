"""api.export: PDF and Excel builders for one completed run.

fpdf2's core fonts are Latin-1 only and raise FPDFUnicodeEncodingException --
not a rendering glitch, a hard crash -- on any character outside that
range, verified live against a bare rupee sign AND a plain em-dash this
module's own code once used in a header string. Every test that touches
build_pdf uses report text containing rupee figures, em/en dashes, curly
quotes, and an ellipsis specifically because those are the characters that
already broke this once during development.
"""

from datetime import date
from io import BytesIO

import openpyxl
import pytest

from api.export import _available_reports, _money, _pdf_safe, build_excel, build_pdf
from api.schemas import (
    AnalysisProfile,
    Reports,
    RunDetail,
    RunStatus,
    TradeLevels,
    Verdict,
)

DAY = date(2026, 8, 12)


def _run(**overrides) -> RunDetail:
    defaults = dict(
        id="abc123",
        ticker="SIEMENS.NS",
        analysis_date=DAY,
        profile=AnalysisProfile.FAST,
        status=RunStatus.COMPLETED,
        created_at="2026-08-12T14:26:16",
        completed_at="2026-08-12T14:30:00",
    )
    defaults.update(overrides)
    return RunDetail(**defaults)


def _full_run() -> RunDetail:
    """A run whose report text deliberately packs in every character class
    that has crashed fpdf2 during development: rupee signs, an em dash, an
    en dash, curly quotes, and an ellipsis."""
    return _run(
        verdict=Verdict(
            rating="Overweight",
            price_target=5099.0,
            time_horizon="3-4 months",
            current_price=4865.5,
            levels=TradeLevels(action="Buy", entry_price=4625.0, stop_loss=4355.0),
        ),
        reports=Reports(
            final_decision=(
                "**Rating**: Overweight\n\n**Executive Summary**: Trim into strength at "
                "₹4,865.5 — entry near ₹4,625, stop – ₹4,355."
            ),
            trader_plan="**Action**: Buy\n\n**Reasoning**: Momentum confirmed at ₹4,865.",
            market="It’s a strong signal… volume confirms the move.",
        ),
    )


# --- _pdf_safe / _money ----------------------------------------------------


@pytest.mark.unit
def test_pdf_safe_replaces_every_character_that_has_actually_crashed_fpdf2():
    text = "₹4,865 — up – it’s “strong”…"

    safe = _pdf_safe(text)

    assert "₹" not in safe
    assert "—" not in safe
    assert "–" not in safe
    assert "’" not in safe
    assert "“" not in safe and "”" not in safe
    assert "…" not in safe
    assert "Rs. 4,865" in safe


@pytest.mark.unit
def test_pdf_safe_falls_back_to_a_placeholder_for_any_character_the_table_does_not_know():
    """The explicit substitution table can never enumerate every character
    LLM-authored text might contain -- confirmed live: a real run's report
    used a "→" arrow, which crashed export.pdf in production even after the
    rupee/dash/quote table above already shipped. This is the general case
    that fix depends on: any character not in the table (a checkmark here,
    but the point is it's arbitrary) must degrade to '?', never raise."""
    text = "confirmed ✓ still safe"

    safe = _pdf_safe(text)

    assert all(ord(ch) < 256 for ch in safe)
    assert "?" in safe


@pytest.mark.unit
def test_money_formats_a_value_and_reports_not_set_for_none():
    assert _money(4865.5, "Rs. ") == "Rs. 4,865.50"
    assert _money(4865.5, "₹") == "₹4,865.50"
    assert _money(None, "Rs. ") == "Not set"


# --- _available_reports -----------------------------------------------------


@pytest.mark.unit
def test_available_reports_skips_unset_fields_and_preserves_group_order():
    run = _run(reports=Reports(final_decision="A", market="B"))  # everything else unset

    result = _available_reports(run)

    assert result == [
        ("Portfolio", "Final decision", "A"),
        ("Analysts", "Market", "B"),
    ]


@pytest.mark.unit
def test_available_reports_is_empty_for_a_run_with_no_reports():
    assert _available_reports(_run()) == []


# --- build_pdf ---------------------------------------------------------------


@pytest.mark.unit
def test_build_pdf_returns_a_real_pdf_for_a_full_run():
    result = build_pdf(_full_run())

    assert isinstance(result, bytes)
    assert result.startswith(b"%PDF")
    assert len(result) > 500


@pytest.mark.unit
def test_build_pdf_does_not_raise_on_a_bare_run_with_no_verdict_or_reports():
    result = build_pdf(_run())

    assert result.startswith(b"%PDF")


@pytest.mark.unit
def test_build_pdf_does_not_raise_when_levels_are_all_null():
    run = _run(
        verdict=Verdict(rating="Hold", price_target=None, time_horizon=None, current_price=None, levels={})
    )

    result = build_pdf(run)

    assert result.startswith(b"%PDF")


# --- build_excel ---------------------------------------------------------


@pytest.mark.unit
def test_build_excel_returns_a_real_workbook_with_both_sheets():
    result = build_excel(_full_run())

    assert isinstance(result, bytes)
    assert result.startswith(b"PK")  # xlsx is a zip archive

    wb = openpyxl.load_workbook(BytesIO(result))
    assert wb.sheetnames == ["Summary", "Full reports"]


@pytest.mark.unit
def test_build_excel_summary_sheet_has_the_verdict_fields():
    wb = openpyxl.load_workbook(BytesIO(build_excel(_full_run())))
    summary = wb["Summary"]

    values = {row[0].value: row[1].value for row in summary.iter_rows(min_col=1, max_col=2)}

    assert values["Ticker"] == "SIEMENS.NS"
    assert values["Rating"] == "Overweight"
    assert values["Action"] == "Buy"
    assert values["Entry"] == "₹4,625.00"  # Excel keeps the real rupee sign, unlike the PDF path


@pytest.mark.unit
def test_build_excel_full_reports_sheet_has_one_row_per_available_report():
    wb = openpyxl.load_workbook(BytesIO(build_excel(_full_run())))
    reports_ws = wb["Full reports"]

    rows = list(reports_ws.iter_rows(min_row=2, values_only=True))
    labels = [row[1] for row in rows]

    assert labels == ["Final decision", "Trader plan", "Market"]
    # Word count column (index 2) is a real count, not zero/placeholder.
    assert all(row[2] > 0 for row in rows)


@pytest.mark.unit
def test_build_excel_does_not_raise_on_a_bare_run():
    result = build_excel(_run())

    wb = openpyxl.load_workbook(BytesIO(result))
    reports_ws = wb["Full reports"]
    assert list(reports_ws.iter_rows(min_row=2)) == []


# --- HTTP layer ------------------------------------------------------------


@pytest.fixture
def client_and_store():
    from fastapi.testclient import TestClient

    from api.dependencies import InMemoryRunStore, get_run_store
    from api.main import create_app

    app = create_app()
    run_store = InMemoryRunStore()
    app.dependency_overrides[get_run_store] = lambda: run_store
    with TestClient(app) as test_client:
        yield test_client, run_store


def _complete(run_store, run_id: str) -> None:
    run_store._runs[run_id] = run_store._runs[run_id].model_copy(
        update={
            "status": RunStatus.COMPLETED,
            "verdict": Verdict(rating="Buy", levels=TradeLevels(action="Buy")),
            "reports": Reports(final_decision="**Rating**: Buy"),
        }
    )


@pytest.mark.unit
def test_export_pdf_endpoint_returns_a_pdf_for_a_completed_run(client_and_store):
    client, run_store = client_and_store
    created_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]
    _complete(run_store, created_id)

    response = client.get(f"/runs/{created_id}/export.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert "SIEMENS.NS" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


@pytest.mark.unit
def test_export_excel_endpoint_returns_a_workbook_for_a_completed_run(client_and_store):
    client, run_store = client_and_store
    created_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]
    _complete(run_store, created_id)

    response = client.get(f"/runs/{created_id}/export.xlsx")

    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.content.startswith(b"PK")


@pytest.mark.unit
@pytest.mark.parametrize("extension", ["pdf", "xlsx"])
def test_export_endpoints_404_for_an_unknown_run(client_and_store, extension):
    client, _store = client_and_store

    response = client.get(f"/runs/does-not-exist/export.{extension}")

    assert response.status_code == 404


@pytest.mark.unit
@pytest.mark.parametrize("extension", ["pdf", "xlsx"])
def test_export_endpoints_404_for_a_run_that_has_not_completed(client_and_store, extension):
    client, _store = client_and_store
    created_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]  # still queued

    response = client.get(f"/runs/{created_id}/export.{extension}")

    assert response.status_code == 404
