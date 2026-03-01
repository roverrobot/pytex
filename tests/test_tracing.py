from pytex import texlive


def test_show_reports_meaning(parser):
    parser.parse("\\def\\foo{a}\\show\\foo")
    log = parser.logContent()
    assert "> \\foo=" in log
    assert "macro:" in log


def test_showthe_reports_expanded_value(parser):
    parser.parse("\\count0=12\\showthe\\count0")
    assert "> 12" in parser.logContent()


def test_showbox_dumps_box_contents(cmr10):
    cmr10.parse("\\setbox1=\\hbox{a}\\showbox1")
    log = cmr10.logContent()
    assert "> \\box1=" in log
    assert "\\hbox(" in log
    assert "\\f a" in log


def test_showbox_respects_breadth_limit(cmr10):
    cmr10.parse("\\showboxbreadth=1\\setbox1=\\hbox{ab}\\showbox1")
    log = cmr10.logContent()
    assert "etc." in log


def test_showlists_dumps_current_list_stack(cmr10):
    cmr10.parse("ab")
    cmr10.parse("\\showlists")
    log = cmr10.logContent()
    assert "> \\showlists" in log
    assert "### list 0" in log
    assert "HList" in log
    assert "\\f a" in log
