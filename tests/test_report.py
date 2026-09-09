"""Reports: both formats, the generated limitations, and the no-leak guarantee."""

from __future__ import annotations

import json

import pytest

from complydoc.audit import COMPONENTS, run_audit
from complydoc.report.html_writer import render_html
from complydoc.report.json_writer import to_dict, write_json
from tests.helpers import FIXTURES

SECRETS = (
    "4111 1111 1111 1111",
    "4111111111111111",
    "AB123456C",
    "jane.doe@example.com",
    "GB82 WEST 1234 5698 7654 32",
    "GB123456782",
    "020 7946 0958",
)


@pytest.fixture(scope="module")
def report(config):
    return run_audit(FIXTURES, config, COMPONENTS, monthly_volume=1000)


@pytest.fixture(scope="module")
def html(report, config):
    return render_html(report, config)


# --- the guarantee ---------------------------------------------------------


def test_no_sensitive_value_reaches_the_html_by_default(html):
    for secret in SECRETS:
        assert secret not in html, f"{secret!r} leaked into the HTML report"


def test_no_sensitive_value_reaches_the_json_by_default(report):
    serialised = json.dumps(to_dict(report))
    for secret in SECRETS:
        assert secret not in serialised, f"{secret!r} leaked into the JSON report"


def test_reveal_is_recorded_and_stamped(config):
    revealed = run_audit(FIXTURES, config, ("sensitive",), reveal=True)
    assert revealed.run.reveal_used is True
    page = render_html(revealed, config)
    assert "unmasked sensitive values" in page
    assert any(x.area == "Masking" for x in revealed.limitations)


def test_never_reveal_categories_stay_masked_even_then(config):
    revealed = run_audit(FIXTURES, config, ("sensitive",), reveal=True)
    page = render_html(revealed, config)
    assert "4111111111111111" not in page
    assert "AB123456C" not in page


# --- self-contained --------------------------------------------------------


def test_html_has_no_external_assets(html):
    import re

    for marker in ("<script src=", "@import", "url(http"):
        assert marker not in html, f"report pulls in an external asset: {marker}"
    # A <link> is allowed only if it carries the asset inline.
    for tag in re.findall(r"<link\b[^>]*>", html):
        assert 'href="data:' in tag, f"link fetches something: {tag}"


def test_report_carries_an_inline_favicon(html):
    assert '<link rel="icon" href="data:image/svg+xml,' in html


def test_html_carries_its_own_stylesheet(html):
    assert "<style>" in html


# --- content ---------------------------------------------------------------


def test_aggregate_section_is_present(report, html):
    assert report.aggregate is not None
    assert report.aggregate.documents_audited > 0
    assert "Summary" in html
    assert "Documents audited" in html


def test_every_document_gets_a_section(report, html):
    for document in report.documents:
        assert document.relative_path in html


def test_weights_are_printed_whenever_a_score_is(report, html):
    assert report.signal_weights, "scoring is on, so weights must be exposed"
    assert "Weight" in html
    for signal_id, weight in report.signal_weights.items():
        assert signal_id in report.aggregate.signal_distribution
        assert weight >= 0


def test_skipped_files_are_reported_not_silently_dropped(report):
    names = {s.path.name for s in report.skipped}
    assert "broken.pdf" in names
    assert "notes.txt" in names


# --- limitations -----------------------------------------------------------


def test_limitations_are_generated_from_this_run(report):
    areas = {x.area for x in report.limitations}
    assert "Files not examined" in areas
    assert "Pages that could not be read" in areas
    assert "Encrypted documents" in areas
    assert "Table detection" in areas


def test_limitations_name_the_documents_they_apply_to(report):
    entry = next(x for x in report.limitations if x.area == "Encrypted documents")
    assert entry.affected == ["encrypted.pdf"]


def test_running_one_component_says_so_in_the_limitations(config):
    only_sensitive = run_audit(FIXTURES, config, ("sensitive",))
    entry = next(x for x in only_sensitive.limitations if x.area == "Components not run")
    assert "cost" in entry.statement and "difficulty" in entry.statement


def test_a_run_with_everything_available_does_not_claim_missing_components(report):
    assert not any(x.area == "Components not run" for x in report.limitations)


def test_output_cost_is_declared_out_of_scope(report):
    entry = next(x for x in report.limitations if x.area == "Cost scope")
    assert "Only input cost" in entry.statement


def test_extrapolation_states_its_assumption(report):
    entry = next(x for x in report.limitations if x.area == "Volume extrapolation")
    assert entry.severity == "important"


# --- machine readable ------------------------------------------------------


def test_json_round_trips(report, tmp_path):
    path = write_json(report, tmp_path / "r.json")
    data = json.loads(path.read_text())
    assert data["run"]["schema_version"] == report.run.schema_version
    assert len(data["documents"]) == len(report.documents)
    assert "limitations" in data


def test_json_is_stable_for_diffing(report, tmp_path):
    first = write_json(report, tmp_path / "a.json").read_text()
    second = write_json(report, tmp_path / "b.json").read_text()
    assert first == second


def test_config_digest_is_recorded_so_runs_are_comparable(report, config):
    assert report.run.config_digest == config.digest


def test_offline_status_is_recorded(report):
    assert report.run.offline_guard in {"armed", "not_armed"}


# --- opt-in page images ----------------------------------------------------


def test_default_report_embeds_no_page_images(html, report):
    assert report.run.page_images_used is False
    assert "data:image/jpeg" not in html


def test_page_images_are_recorded_in_the_run_options(config):
    """A picture of every page is worth recording, not worth a banner."""
    from complydoc.report.html_writer import render_html

    with_images = run_audit(FIXTURES, config, COMPONENTS, page_images=True)
    assert with_images.run.page_images_used is True
    page = render_html(with_images, config)
    assert "data:image/jpeg" in page
    options = page.split('class="opts">')[1].split("<")[0]
    assert "--page-images" in options


# --- filter and pagination -------------------------------------------------


def test_report_ships_its_own_filter_and_pagination(html):
    assert 'id="filelist"' in html
    assert 'id="docfilter"' in html
    assert "data-paginate" in html
    assert "<script>" in html


def test_the_file_filter_indexes_facts_not_prose(html):
    """Matching the whole section text made "rotated" return every document, because
    the explanation of the rotation signal appears in all of them."""
    assert "data-search=" in html
    index = html.split('data-search="')[1].split('"')[0]
    assert "rotated" not in index or "rotated_scan" in index
    assert "stored sideways" not in index


def test_the_script_is_inline_not_fetched(html):
    assert "<script src=" not in html


def test_content_is_present_without_scripting(html, report):
    """Filtering is an enhancement; every document must be in the markup already."""
    for document in report.documents:
        assert document.relative_path in html


# --- opt-in extracted text -------------------------------------------------


def test_extracted_text_is_absent_by_default(report, html):
    assert report.run.extracted_text_used is False
    assert all(not d.extracted_text for d in report.documents)
    assert '<details class="text">' not in html


def test_extracted_text_is_included_and_stamped_when_asked_for(config):
    from complydoc.report.html_writer import render_html

    with_text = run_audit(FIXTURES, config, COMPONENTS, extracted_text=True)
    assert with_text.run.extracted_text_used is True
    document = next(d for d in with_text.documents if d.relative_path == "sensitive_sample.pdf")
    assert document.extracted_text
    assert "EMPLOYEE RECORD" in document.extracted_text[0].text

    page = render_html(with_text, config)
    assert "EMPLOYEE RECORD" in page, "the text belongs beside the page it was read from"
    options = page.split('class="opts">')[1].split("<")[0]
    assert "--extracted-text" in options


def test_extracted_text_records_how_each_page_was_read(config):
    with_text = run_audit(FIXTURES, config, COMPONENTS, extracted_text=True)
    scanned = next(d for d in with_text.documents if d.relative_path == "scanned_page.pdf")
    assert scanned.extracted_text[0].source == "none"
    assert scanned.extracted_text[0].characters == 0


def test_very_long_pages_are_truncated_not_dropped(config):
    """One enormous document must not make the report unopenable."""
    from complydoc.audit import _MAX_TEXT_CHARS

    with_text = run_audit(FIXTURES, config, COMPONENTS, extracted_text=True)
    for document in with_text.documents:
        for page in document.extracted_text:
            assert len(page.text) <= _MAX_TEXT_CHARS
            if page.truncated:
                assert page.characters > _MAX_TEXT_CHARS


# --- the four pages --------------------------------------------------------


def test_report_has_four_pages(html):
    import re

    assert re.findall(r'<section data-page id="(\w+)"', html) == [
        "summary",
        "cost",
        "security",
        "documents",
    ]


def test_every_page_is_reachable_from_the_nav(html):
    for page in ("summary", "cost", "security", "documents"):
        assert f'data-tab="{page}"' in html


def test_only_the_first_page_starts_visible(html):
    import re

    sections = re.findall(r'<section data-page id="(\w+)"( hidden)?>', html)
    assert sections[0] == ("summary", "")
    assert all(hidden for _, hidden in sections[1:])


def test_tabs_do_not_depend_on_the_url_hash(html):
    """A data: URL or sandboxed mail preview never reports a hash."""
    assert 'a.addEventListener("click"' in html
    assert "preventDefault" in html


def test_limitations_stay_in_the_json_not_the_html(html, report):
    """The list is written for an agent to act on; the HTML is read by people.

    The facts that change a business conclusion are surfaced in their own right:
    unverified prices get a callout, unread pages appear on their document.
    """
    assert report.limitations, "the run still records them"
    assert "What this run could not tell you" not in html
    assert "not a standard disclaimer" not in html


def test_decision_changing_facts_survive_in_the_html(html, report):
    if report.staleness_warnings:
        assert "Unverified prices" in html
    unread = [d for d in report.documents if d.sensitive and d.sensitive.unreadable_pages]
    if unread:
        flat = " ".join(html.split())
        assert "not searched" in flat
        assert "nothing was found there because nothing looked" in flat.lower()


def test_summary_leads_with_the_three_business_figures(html):
    summary = html.split('id="summary"')[1].split("<section")[0]
    assert "Cost per 1,000 documents" in summary
    assert "Average quality" in summary
    assert "Sensitive items per document" in summary


def test_cost_page_carries_the_charts(html):
    cost = html.split('id="cost"')[1].split("<section")[0]
    assert 'class="chart"' in cost
    assert "Text + local OCR" in cost


def test_reach_is_on_the_bars_not_in_a_second_table(html):
    """Cost alone favours the text layer; reach is what stops that misleading."""
    cost = html.split('id="cost"')[1].split("<section")[0]
    assert "The same numbers" not in cost
    assert 'tspan fill="var(--faint)"' in cost, "each bar should carry its reach"
    assert "reaches" in cost, "the note belongs on hover"


def test_charts_can_be_filtered_by_provider(html, report):
    cost = html.split('id="cost"')[1].split("<section")[0]
    providers = {m.provider for d in report.documents if d.cost for m in d.cost.models}
    if len(providers) > 1:
        assert 'id="providers"' in cost
        for provider in providers:
            assert f'data-provider="{provider}"' in cost


def test_reveal_still_gets_a_banner(config):
    """--reveal prints identifiers verbatim; that is not a footnote."""
    from complydoc.report.html_writer import render_html

    revealed = run_audit(FIXTURES, config, ("sensitive",), reveal=True)
    page = render_html(revealed, config)
    assert "unmasked sensitive values" in page


def test_security_page_lists_every_occurrence(html, report):
    security = html.split('id="security"')[1].split("<section")[0]
    assert "Every occurrence" in security
    assert "Document" in security


def test_documents_page_holds_the_explorer(html):
    documents = html.split('id="documents"')[1].split("</main>")[0]
    assert 'id="filelist"' in documents
    assert 'class="viewer"' in documents
    for view in ("pages", "signals"):
        assert f'data-view="{view}"' in documents


def test_documents_page_carries_no_security_table(html):
    """Sensitive findings belong on the security page; the explorer is about content."""
    documents = html.split('id="documents"')[1].split("</main>")[0]
    assert "Matched because" not in documents


def test_difficulty_is_flagged_on_the_document_itself(html):
    documents = html.split('id="documents"')[1].split("</main>")[0]
    assert 'class="doc-meta"' in documents
    assert 'class="concerns"' in documents, "poor signals belong on the document"
    assert 'class="pcap"' in documents, "and the per-page facts on the page"


def test_colour_marks_the_exception_rather_than_every_category(html):
    """Green, amber and red on every rating is what made it look generated."""
    styles = html.split("<style>")[1].split("</style>")[0]
    assert "--attn:" in styles
    for gone in ("--good-bg", "--fair-bg", "--poor-bg"):
        assert gone not in styles, f"{gone} is still defined"
    assert "background: var(--good-bg)" not in styles


def test_every_signal_carries_its_explanation(html):
    """A distribution of ratings means nothing without saying what each measures."""
    table = html.split("Difficulty signals across the whole folder")[1].split("</table>")[0]
    assert "Why it matters" in table
    import re

    explanations = re.findall(r'<td class="why">([^<]{10,})</td>', table)
    assert len(explanations) >= 18


def test_report_does_not_explain_its_own_flags(html):
    """Instructions for command line flags are not what a reader is here for."""
    for phrase in ("Run with <code>--page-images", "Weights come from"):
        assert phrase not in html


def test_signal_explanations_are_one_sentence(config):
    """The brief asks for one plain sentence, and prose is what buries a table."""
    from complydoc.difficulty.registry import all_signals

    for signal in all_signals():
        assert signal.why.count(".") <= 1, f"{signal.id} runs to more than one sentence"
        assert len(signal.why) <= 100, f"{signal.id} is {len(signal.why)} characters"


# --- copy quality ----------------------------------------------------------


def test_no_parenthesised_plurals_reach_the_reader(html):
    """ "3 page(s)" reads like a template, not like something someone wrote."""
    import re

    found = re.findall(r"\w+\(s\)", html)
    assert not found, f"parenthesised plurals in the report: {sorted(set(found))}"


def test_footer_carries_the_run_and_the_guarantee(html):
    footer = html.split("<footer>")[1]
    assert "No document content left this machine" in footer
    assert "Audited" in footer and "Finished" in footer
    assert "network guard" in footer


def test_run_options_record_exactly_what_was_asked_for(config):
    from complydoc.report.html_writer import render_html

    report = run_audit(FIXTURES, config, COMPONENTS, ocr=False, monthly_volume=500)
    options = render_html(report, config).split('class="opts">')[1].split("<")[0]
    assert "--no-ocr" in options
    assert "--monthly-volume 500" in options
    assert "--page-images" not in options
    assert "--reveal" not in options


def test_filtering_the_chart_animates_rather_than_snapping(html):
    """A viewBox is an attribute, so it has to be tweened, not CSS-transitioned."""
    assert "requestAnimationFrame" in html
    assert "prefers-reduced-motion" in html
    assert ".grp.out" in html, "filtered rows fade rather than vanishing"


def test_the_summary_leads_with_preparation_time(html):
    summary = html.split('id="summary"')[1].split("<section")[0]
    assert "Local preparation" in summary
    assert "before anything reaches a model" in summary


def test_the_footer_records_the_observed_rates(html):
    footer = html.split("<footer>")[1]
    assert "Took" in footer
    assert "a page" in footer
