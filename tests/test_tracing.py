from pytex import texlive
from pytex.glue import Glue
from pytex.dimen import Dimen

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
        "\\textfont3=\\tenex \\scriptfont3=\\tenex \\scriptscriptfont3=\\tenex"
    )


def test_show_reports_meaning(parser):
    parser.parse("\\def\\foo{a}\\show\\foo")
    log = parser.logContent()
    assert "> \\foo=macro:->a" in log


def test_showthe_reports_expanded_value(parser):
    parser.parse("\\count0=12\\showthe\\count0")
    assert "> 12" in parser.logContent()


def test_showbox_dumps_box_contents(cmr10):
    cmr10.parse("\\setbox1=\\hbox{a}\\showbox1")
    log = cmr10.logContent()
    assert "> \\box1=" in log
    assert "\\hbox(" in log
    assert "glyph cluster 'a'" in log


def test_showbox_respects_breadth_limit(cmr10):
    cmr10.parse("\\showboxbreadth=1\\setbox1=\\hbox{ab}\\showbox1")
    log = cmr10.logContent()
    assert "etc." in log


def test_box_meaning_reports_glue_set(cmr10):
    cmr10.parse("\\setbox1=\\hbox to 20pt{a\\hfil}")
    box = cmr10.box[1]
    box.typeset(cmr10, [])
    assert "glue set" in box.meaning(cmr10)


def test_literal_glue_is_unnamed_in_tracing(cmr10):
    cmr10.parse("\\setbox1=\\hbox to 20pt{a\\hfil}\\showbox1")
    log = cmr10.logContent()
    assert "\\glue(\\hfil)" not in log


def test_showlists_dumps_current_list_stack(cmr10):
    cmr10.parse("ab")
    cmr10.parse("\\showlists")
    log = cmr10.logContent()
    assert "> \\showlists" in log
    assert "### list 0" in log
    assert "Paragraph" in log
    assert "glyph cluster 'a'" in log


def test_showlists_omits_main_vlist_wrapper(cmr10):
    cmr10.parse("ab\\par\\showlists")
    log = cmr10.logContent()
    assert "VList(outer)" not in log
    assert "### list 0" not in log
    assert "\\hbox" in log


def test_showlists_expands_inline_math_nodes(cmr10):
    _init_math_fonts(cmr10)
    cmr10.parse("$a$\\showlists")
    log = cmr10.logContent()
    assert "\\mathon" in log
    assert "\\mathoff" in log
    assert "\\teni a" in log


def test_showlists_expands_display_math_nodes(cmr10):
    _init_math_fonts(cmr10)
    cmr10.layout["baselineskip"] = Glue(Dimen(12))
    cmr10.parse("\\hsize=200pt $$a$$\\showlists")
    log = cmr10.logContent()
    assert "\\glue(\\abovedisplayshortskip)" in log
    assert "\\glue(\\baselineskip)" in log #
    assert "\\glue(\\belowdisplayshortskip)" in log
    assert ", display" in log
    assert "\\teni a" in log


def test_tracingoutput_logs_shipped_box(parser):
    parser.parse("\\tracingoutput=1\\shipout\\vbox{\\hrule}")
    parser.end()
    log = parser.logContent()
    assert "Completed box being shipped out [" in log
    assert "\\vbox(" in log
    assert "\\rule(" in log
