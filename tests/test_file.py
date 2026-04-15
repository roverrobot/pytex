import pytest
from pytex import html_reflow
html_reflow.mod.init = None
from pytex import texlive
from pytex import pipes
from pytex.resolver import InMemoryTextFile
from pytex import node as nd
from pytex import macro


@pytest.fixture()
def read_tex(parser):
    parser.resolver.in_memory_files["read.tex"] = InMemoryTextFile("123{4\n56}7}8")
    return parser


def test_openin_immediate(example_tex):
    # open a file for reading
    example_tex.parse("\\immediate\\openin 0=example.tex")
    file = example_tex.globals["openin"][0]
    assert file is not None
    s = file.readline()
    assert s == "Hello, world!\n"
    example_tex.parse("\\closein 0")
    file = example_tex.globals["openin"][0]
    assert file is None


def test_openin(example_tex):
    example_tex.parse("\\openin 0=example.tex")
    file = example_tex.globals["openin"][0]
    assert file is not None
    s = file.readline()
    assert s == "Hello, world!\n"
    example_tex.parse("\\closein 0")
    file = example_tex.globals["openin"][0]
    assert file is None


def test_openout_immediate(parser):
    # open a file for reading
    parser.parse("\\def\\a{123}")
    parser.parse("\\immediate\\openout 1=output.tex")
    file = parser.globals["openout"][1]
    assert file is not None
    assert "output.tex" in parser.resolver.in_memory_files
    parser.parse("\\immediate\\write1{\\a xyz}")
    parser.parse("\\immediate\\closeout 1")
    file = parser.globals["openout"][1]
    assert file is None
    file = parser.resolver.in_memory_files["output.tex"]
    assert file.content == "123xyz\n"


def test_openout_preserves_aux_macro_hashes(parser):
    parser.parse(
        "\\let\\a=\\relax"
        "\\immediate\\openout 1=output-hash.tex"
        "\\immediate\\write1{\\string\\gdef\\string\\a\\string#1{\\string#1}}"
        "\\immediate\\closeout 1"
    )
    file = parser.resolver.in_memory_files["output-hash.tex"]
    assert file.content == "\\gdef\\a#1{#1}\n"


def test_openout_preserves_protected_macros(parser):
    parser.parse("\\def\\a{123}")
    parser.lookup("\\a").protected = True
    parser.parse("\\immediate\\openout 1=output-protected.tex")
    parser.parse("\\immediate\\write1{\\a}")
    parser.parse("\\immediate\\closeout 1")
    file = parser.resolver.in_memory_files["output-protected.tex"]
    assert file.content == "\\a \n"


def test_immediate_write_stops_before_outer_input(collector):
    collector.parse("\\def\\a{123}\\immediate\\openout 1=output-boundary.tex\\immediate\\write1{\\a}\\a\\immediate\\closeout 1")
    assert collector.getString() == "123"
    file = collector.resolver.in_memory_files["output-boundary.tex"]
    assert file.content == "123\n"


def test_openout(parser):
    parser.parse("\\def\\a{123}\\openout 1=output1.tex \\write1{\\a xyz}\\closeout 1")
    file = parser.globals["openout"][1]
    assert file is None
    top = parser.lists[-1]
    assert len(top) == 3
    op = top[0]
    assert op.node_type == nd.NODE_TYPE.WHATSIT
    op.output(parser, None)
    file = parser.globals["openout"][1]
    assert file is not None
    assert "output1.tex" in parser.resolver.in_memory_files
    op = top[1]
    assert op.node_type == nd.NODE_TYPE.WHATSIT
    op.output(parser, None)
    op = top[2]
    assert op.node_type == nd.NODE_TYPE.WHATSIT
    op.output(parser, None)
    file = parser.globals["openout"][1]
    assert file is None
    file = parser.resolver.in_memory_files["output1.tex"]
    assert file.content == "123xyz\n"


def test_deferred_shipout_flushes_write_before_closeout(parser, tmp_path):
    parser.shipout = parser.shipout.__class__(parser, str(tmp_path / "shipwrite"))
    parser.parse("\\immediate\\openout 1=output2.tex\\shipout\\vbox{\\write1{abc}}\\closeout 1")
    parser.end()
    file = parser.resolver.in_memory_files["output2.tex"]
    assert file.content == "abc\n"


def test_html_reflow_shipout_flushes_write_before_closeout(parser):
    html_reflow.font_subst.installFontSubstitution(parser)
    parser.shipout = html_reflow.HTMLReflowBackend(parser)
    parser.parse("\\immediate\\openout 1=output2.tex\\shipout\\vbox{\\write1{abc}}\\closeout 1")
    parser.end()
    file = parser.resolver.in_memory_files["output2.tex"]
    assert file.content == "abc\n"


@pytest.mark.parametrize("cmd", ["\\message", "\\errmessage"])
def test_message_family_preserves_single_hash(parser, cmd):
    parser.parse(f"{cmd}{{\\string#}}")
    assert parser.logContent().strip() == "#"


def test_read(read_tex):
    read_tex.parse("\\openin 0=read.tex \\read 0 to \\a\\closein 0")
    a = read_tex.equitable["\\a"]
    assert isinstance(a, macro.Macro)
    assert len(a.replacement) == 10


def test_read_from_pipe_command(parser):
    def handler(resolver, args):
        assert args == ["probe"]
        return "12{3}\n"

    pipes.registerPipeCommand("fakepipe", handler)
    try:
        parser.parse('\\openin 0="|fakepipe probe" \\read 0 to \\a\\closein 0')
    finally:
        pipes.unregisterPipeCommand("fakepipe")
    a = parser.equitable["\\a"]
    assert isinstance(a, macro.Macro)
    assert "".join(t.name for t in a.replacement) == "12{3} "


def test_ifeof(read_tex):
    read_tex.parse("\\openin 0=read.tex \\count0=\\ifeof 0 1\\else -1\\fi")
    assert read_tex.count[0] == -1
    read_tex.parse("\\count0 =\\ifeof 1 1\\else -1\\fi\\closein 0")
    assert read_tex.count[0] == 1
    read_tex.parse("\\count0 =\\ifeof -1 1\\else -1\\fi\\closein 0")
    assert read_tex.count[0] == 1
    read_tex.parse("\\count0 =\\ifeof 18 1\\else -1\\fi\\closein 0")
    assert read_tex.count[0] == 1
