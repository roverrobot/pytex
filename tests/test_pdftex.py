import datetime
import hashlib
import os
import types
import pytest
from pytex.parser import Parser
from pytex.typeset.shipout import Shipout
from pytex.token import CATCODE
from pytex.resolver import InMemoryTextFile


@pytest.fixture()
def parser(tmp_path, monkeypatch):
    from pytex import pdftex  # register pdftex module for this test file only
    monkeypatch.chdir(tmp_path)
    p = Parser()
    p.resolver.output_in_memory = True
    p.shipout = Shipout(p)
    p.catcode[ord("{")] = CATCODE.BEGIN_GROUP
    p.catcode[ord("}")] = CATCODE.END_GROUP
    p.catcode[ord("$")] = CATCODE.MATH_SHIFT
    p.catcode[ord("&")] = CATCODE.ALIGNMENT_TAB
    p.catcode[ord("#")] = CATCODE.PARAMETER
    p.catcode[ord("^")] = CATCODE.SUPERSCRIPT
    p.catcode[ord("_")] = CATCODE.SUBSCRIPT
    yield p
    p.close()


def addChar(self, c):
    self.tokens += c


def addSpace(self):
    self.tokens += " "


def getString(self):
    s = self.tokens
    self.tokens = ""
    return s


@pytest.fixture()
def collector(parser):
    parser.tokens = ""
    parser.addChar = types.MethodType(addChar, parser)
    parser.addSpace = types.MethodType(addSpace, parser)
    parser.getString = types.MethodType(getString, parser)
    return parser


@pytest.fixture()
def example_tex(parser):
    parser.resolver.in_memory_files["example.tex"] = InMemoryTextFile("Hello, world!\n")
    return parser


def test_pdfmdfivesum_hashes_expanded_general_text(collector):
    collector.parse("\\def\\a{ab}\\pdfmdfivesum{\\a}")
    assert collector.getString().strip() == hashlib.md5(b"ab").hexdigest().upper()


def test_pdfmdfivesum_file_hashes_general_text_filename(collector, example_tex):
    collector.parse("\\pdfmdfivesum file {example.tex}")
    expected = hashlib.md5(b"Hello, world!\n").hexdigest().upper()
    assert collector.getString().strip() == expected


def test_mdfivesum_alias_matches_pdftex_primitive(collector):
    collector.parse("\\mdfivesum{abc}")
    assert collector.getString().strip() == hashlib.md5(b"abc").hexdigest().upper()


def _pdf_date_string(timestamp: float) -> str:
    dt = datetime.datetime.fromtimestamp(timestamp).astimezone()
    s = dt.strftime("D:%Y%m%d%H%M%S")
    offset = dt.utcoffset()
    if offset is None:
        return s
    seconds = int(offset.total_seconds())
    if seconds == 0:
        return s + "Z"
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    return f"{s}{sign}{hours:02d}'{minutes:02d}'"


def test_pdffilemoddate_reports_timestamp_for_cwd_file(collector, tmp_path):
    path = tmp_path / "tt.log"
    path.write_text("log\n")
    collector.parse("\\pdffilemoddate{tt.log}")
    assert collector.getString().strip() == _pdf_date_string(os.path.getmtime(path))


def test_pdffilemoddate_missing_file_expands_to_nothing(collector):
    collector.parse("A\\pdffilemoddate{missing.log}B")
    assert collector.getString().strip() == "AB"


def test_pdffilesize_extensionless_missing_file_expands_to_nothing(collector):
    collector.parse("A\\pdffilesize{missing}B")
    assert collector.getString().strip() == "AB"


def test_pdffiledump_reads_requested_hex_slice(collector, tmp_path):
    path = tmp_path / "dump.bin"
    path.write_bytes(bytes([0x10, 0xAB, 0xCD, 0xEF]))
    collector.parse("\\pdffiledump offset 1 length 2 {dump.bin}")
    assert collector.getString().strip() == "ABCD"


def test_ifincsname_tracks_csname_scanning(collector):
    collector.parse("\\def\\T{yes}\\ifincsname T\\else F\\fi\\csname\\ifincsname T\\else F\\fi\\endcsname")
    assert collector.getString().strip() == "Fyes"


def test_ifpdfprimitive_checks_original_control_sequence(collector):
    collector.parse("\\ifpdfprimitive\\def T\\else F\\fi\\let\\foo\\def\\ifpdfprimitive\\foo T\\else F\\fi")
    assert collector.getString().strip() == "TF"


def test_pdfprimitive_uses_builtin_meaning_for_expandable_and_nonexpandable_primitives(collector):
    collector.parse("{\\let\\iftrue\\iffalse\\pdfprimitive\\iftrue T\\else F\\fi}"
                    "{\\let\\char\\relax\\pdfprimitive\\char65}")
    assert collector.getString().strip() == "TA"


def test_pdfprimitive_ignores_never_primitive_control_sequences(collector):
    collector.parse("A\\pdfprimitive\\foo B")
    assert collector.getString().strip() == "AB"
