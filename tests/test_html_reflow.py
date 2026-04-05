import re

from pytex import html_reflow
from pytex import texlive


def _normalize(text):
    return re.sub(r"\s+", " ", text)


def _init_math_fonts(parser):
    parser.parse(
        "\\font\\tenrm=cmr10 "
        "\\font\\sevenrm=cmr7 "
        "\\font\\fiverm=cmr5 "
        "\\font\\teni=cmmi10 "
        "\\font\\seveni=cmmi7 "
        "\\font\\fivei=cmmi5 "
        "\\font\\tensy=cmsy10 "
        "\\font\\sevensy=cmsy7 "
        "\\font\\fivesy=cmsy5 "
        "\\font\\tenex=cmex10 "
        "\\skewchar\\teni='177 \\skewchar\\seveni='177 \\skewchar\\fivei='177 "
        "\\skewchar\\tensy='60 \\skewchar\\sevensy='60 \\skewchar\\fivesy='60 "
        "\\textfont1=\\teni \\scriptfont1=\\seveni \\scriptscriptfont1=\\fivei "
        "\\textfont2=\\tensy \\scriptfont2=\\sevensy \\scriptscriptfont2=\\fivesy "
        "\\textfont3=\\tenex \\scriptfont3=\\tenex \\scriptscriptfont3=\\tenex "
        "\\mathchardef\\beta=\"010C "
        "\\mathchardef\\dagger=\"0279"
    )


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
    assert '<p class="paragraph indent"' in html
    assert 'style="font-size:' in html
    assert ">1 Figure</p>" in html
    assert "<h1" not in html
    assert "<h2" not in html


def test_html_reflow_preserves_inline_font_runs(cmr10):
    cmr10.shipout = html_reflow.HTMLReflowBackend(cmr10)
    cmr10.parse(
        r"\font\b=cmbx10 "
        r"\font\i=cmti10 "
        r"A {\b B} {\i C}\par",
        jobname="reflow-inline-fonts",
    )
    cmr10.end()
    html = cmr10.resolver.in_memory_files["reflow-inline-fonts.html"].content
    assert '<p class="paragraph indent">A' in html
    assert 'data-tex-font="cmbx10"' in html
    assert 'style="font-weight:bold"' in html
    assert 'data-tex-font="cmti10"' in html
    assert 'style="font-style:italic"' in html


def test_html_reflow_preserves_raw_special_markers(cmr10):
    cmr10.shipout = html_reflow.HTMLReflowBackend(cmr10)
    cmr10.parse(r"\special{foo}", jobname="reflow-special")
    cmr10.end()
    html = cmr10.resolver.in_memory_files["reflow-special.html"].content
    assert 'class="tex-special"' in html
    assert 'data-tex-special="foo"' in html


def test_html_reflow_maps_dvipdfm_link_specials_to_html_anchor(cmr10):
    cmr10.shipout = html_reflow.HTMLReflowBackend(cmr10)
    cmr10.parse(
        r"\special{pdf:dest (target.1) [@thispage /XYZ @xpos @ypos null]}"
        r"x"
        r"\special{pdf: bann<< /Type/Annot /Subtype/Link /A<< /S/GoTo /D(target.1) >> >>}"
        r"a"
        r"\special{pdf: eann}\par",
        jobname="reflow-link-special",
    )
    cmr10.end()
    html = cmr10.resolver.in_memory_files["reflow-link-special.html"].content
    assert 'id="target.1"' in html
    assert '<a href="#target.1" class="tex-link">a</a>' in html


def test_html_reflow_uses_raw_paragraph_nodes_for_math_and_breaks(cmr10):
    _init_math_fonts(cmr10)
    cmr10.shipout = html_reflow.HTMLReflowBackend(cmr10)
    cmr10.parse(
        r"\noindent A$^{1*}$ and B$^{2\dagger}$\penalty10000 C\par",
        jobname="reflow-raw-math-breaks",
    )
    cmr10.end()
    html = cmr10.resolver.in_memory_files["reflow-raw-math-breaks.html"].content
    assert '<sup><span class="math-atom">1</span><span class="math-atom">*</span></sup>' in html
    assert '<sup><span class="math-atom">2</span><span class="math-atom">†</span></sup>' in html
    assert "<br>" in html


def test_html_reflow_renders_display_math_from_raw_math_nodes(cmr10):
    _init_math_fonts(cmr10)
    cmr10.shipout = html_reflow.HTMLReflowBackend(cmr10)
    cmr10.parse(r"$$p_S=1-p_I$$", jobname="reflow-display-math")
    cmr10.end()
    html = cmr10.resolver.in_memory_files["reflow-display-math.html"].content
    assert '<div class="display-math">' in html
    assert "<sub>S</sub>" in html
    assert "<sub>I</sub>" in html
    assert "-" in html


def test_html_reflow_renders_math_from_alignment_cell_raw_nodes(cmr10):
    _init_math_fonts(cmr10)
    cmr10.shipout = html_reflow.HTMLReflowBackend(cmr10)
    cmr10.parse(r"\halign{$#$\cr \beta\cr}", jobname="reflow-halign-math")
    cmr10.end()
    html = cmr10.resolver.in_memory_files["reflow-halign-math.html"].content
    assert "<table class=\"alignment\">" in html
    assert "β" in html
