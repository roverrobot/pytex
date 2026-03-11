import pytest
from pytex import texlive
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
    file = example_tex.state.globals["openin"][0]
    assert file is not None
    s = file.readline()
    assert s == "Hello, world!\n"
    example_tex.parse("\\closein 0")
    file = example_tex.state.globals["openin"][0]
    assert file is None


def test_openin(example_tex):
    example_tex.parse("\\openin 0=example.tex")
    file = example_tex.state.globals["openin"][0]
    assert file is not None
    s = file.readline()
    assert s == "Hello, world!\n"
    example_tex.parse("\\closein 0")
    file = example_tex.state.globals["openin"][0]
    assert file is None


def test_openout_immediate(parser):
    # open a file for reading
    parser.parse("\\def\\a{123}")
    parser.parse("\\immediate\\openout 1=output.tex")
    file = parser.state.globals["openout"][1]
    assert file is not None
    assert "output.tex" in parser.resolver.in_memory_files
    parser.parse("\\immediate\\write1{\\a xyz}")
    parser.parse("\\immediate\\closeout 1")
    file = parser.state.globals["openout"][1]
    assert file is None
    file = parser.resolver.in_memory_files["output.tex"]
    assert file.content == "123xyz\n"


def test_openout(parser):
    parser.parse("\\def\\a{123}\\openout 1=output1.tex \\write1{\\a xyz}\\closeout 1")
    file = parser.state.globals["openout"][1]
    assert file is None
    top = parser.lists[-1]
    assert len(top) == 3
    op = top[0]
    assert op.node_type == nd.NODE_TYPE.WHATSIT
    op.output(parser, None)
    file = parser.state.globals["openout"][1]
    assert file is not None
    assert "output1.tex" in parser.resolver.in_memory_files
    op = top[1]
    assert op.node_type == nd.NODE_TYPE.WHATSIT
    op.output(parser, None)
    op = top[2]
    assert op.node_type == nd.NODE_TYPE.WHATSIT
    op.output(parser, None)
    file = parser.state.globals["openout"][1]
    assert file is None
    file = parser.resolver.in_memory_files["output1.tex"]
    assert file.content == "123xyz\n"


def test_deferred_shipout_flushes_write_before_closeout(parser, tmp_path):
    parser.shipout = parser.shipout.__class__(parser, str(tmp_path / "shipwrite"))
    parser.parse("\\immediate\\openout 1=output2.tex\\shipout\\vbox{\\write1{abc}}\\closeout 1")
    parser.end()
    file = parser.resolver.in_memory_files["output2.tex"]
    assert file.content == "abc\n"


def test_read(read_tex):
    read_tex.parse("\\openin 0=read.tex \\read 0 to \\a\\closein 0")
    a = read_tex.state.equitable["\\a"]
    assert isinstance(a, macro.Macro)
    assert len(a.replacement) == 10


def test_ifeof(read_tex):
    read_tex.parse("\\openin 0=read.tex \\count0=\\ifeof 0 1\\else -1\\fi")
    assert read_tex.state.count[0] == -1
    read_tex.parse("\\count0 =\\ifeof 1 1\\else -1\\fi\\closein 0")
    assert read_tex.state.count[0] == 1
    read_tex.parse("\\count0 =\\ifeof -1 1\\else -1\\fi\\closein 0")
    assert read_tex.state.count[0] == 1
    read_tex.parse("\\count0 =\\ifeof 18 1\\else -1\\fi\\closein 0")
    assert read_tex.state.count[0] == 1
