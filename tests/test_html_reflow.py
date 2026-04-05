import re

from pytex import html_reflow
from pytex import texlive


def _normalize(text):
    return re.sub(r"\s+", " ", text)


def test_html_reflow_merges_owned_line_boxes_into_one_paragraph(cmr10):
    cmr10.shipout = html_reflow.HTMLReflowBackend(cmr10)
    cmr10.parse(r"\hsize=20pt a a a a a a a a", jobname="reflow-para")
    cmr10.end()
    html = cmr10.resolver.in_memory_files["reflow-para.html"].content
    assert html.count('<p class="paragraph indent">') == 1
    assert "a a a a a a a a" in _normalize(html)


def test_html_reflow_renders_insert_as_note(cmr10):
    cmr10.shipout = html_reflow.HTMLReflowBackend(cmr10)
    cmr10.parse(r"\insert2{\hbox{note}}", jobname="reflow-note")
    cmr10.end()
    html = cmr10.resolver.in_memory_files["reflow-note.html"].content
    assert '<aside class="note">note</aside>' in html


def test_html_reflow_renders_halign_as_table(cmr10):
    cmr10.shipout = html_reflow.HTMLReflowBackend(cmr10)
    cmr10.parse(r"\halign{#&#\cr a&b\cr c&d\cr}", jobname="reflow-table")
    cmr10.end()
    html = cmr10.resolver.in_memory_files["reflow-table.html"].content
    assert "<table class=\"alignment\">" in html
    assert "<td>a</td>" in html
    assert "<td>b</td>" in html
    assert "<td>c</td>" in html
    assert "<td>d</td>" in html


def test_html_reflow_preserves_paragraph_font_size_without_heading_inference(cmr10):
    cmr10.shipout = html_reflow.HTMLReflowBackend(cmr10)
    cmr10.parse(
        r"\font\big=cmr10 at 17.28pt "
        r"{\big 1 Figure}\par "
        r"Body text",
        jobname="reflow-font-size",
    )
    cmr10.end()
    html = cmr10.resolver.in_memory_files["reflow-font-size.html"].content
    assert '<p class="paragraph indent" style="font-size:' in html
    assert ">1 Figure</p>" in html
    assert "<h1" not in html
    assert "<h2" not in html
