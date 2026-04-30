import pytest

from pytex import opentype
from pytex import mmode
from pytex import lists
from pytex.font_backend import FontSpec
from pytex.token import CATCODE


@pytest.fixture(scope="module", autouse=True)
def _enable_xetex_module():
    from pytex import xetex  # register xetex module for this test file


def test_xetex_version_primitives_expand_like_engine_identity(collector):
    collector.parse("\\number\\XeTeXversion\\XeTeXrevision")
    assert collector.getString().strip() == "0.999995"


def test_xetex_font_name_parser_marks_bracketed_file_specs(parser):
    spec = parser.parseFontName("[myfont.ttc:2]/OT:script=latn;+liga")

    assert spec == FontSpec(
        "myfont.ttc",
        lookup="file",
        font_number=2,
        options="/OT",
        features="script=latn;+liga",
    )


def test_xetex_bracketed_extensionless_font_file_loads(parser):
    handle = parser.resolver.openIn("lmroman10-regular", "fonts/opentype")
    if handle is None:
        pytest.skip("lmroman10-regular.otf not found")
    handle.close()

    parser.parse('\\font\\f="[lmroman10-regular]" at 10pt')

    font = parser.equitable["\\f"]
    assert font.backend.kind == "opentype"
    assert font.backend.name == "lmroman10-regular"
    assert font.backend.path.endswith("lmroman10-regular.otf")


def test_xetex_font_file_suffixes_are_ignored_for_lookup(parser):
    handle = parser.resolver.openIn("lmroman10-regular.otf", "fonts/opentype")
    if handle is None:
        pytest.skip("lmroman10-regular.otf not found")
    handle.close()

    parser.parse('\\font\\f="[lmroman10-regular.otf]/OT:script=latn;+liga" at 10pt')

    font = parser.equitable["\\f"]
    assert font.backend.kind == "opentype"
    assert font.backend.name == "lmroman10-regular.otf"
    assert font.backend.path.endswith("lmroman10-regular.otf")


def test_xetex_name_prefix_forces_system_font_lookup(parser, monkeypatch):
    handle = parser.resolver.openIn("lmroman10-regular.otf", "fonts/opentype")
    if handle is None:
        pytest.skip("lmroman10-regular.otf not found")
    path = handle.name
    handle.close()

    @classmethod
    def fake_system_path(cls, name):
        return (path, 0) if name == "Latin Modern Roman" else None

    monkeypatch.setattr(opentype.OpenTypeBackend, "_systemFontPath", fake_system_path)
    parser.parse('\\font\\f="name:Latin Modern Roman" at 10pt')

    font = parser.equitable["\\f"]
    assert font.backend.kind == "opentype"
    assert font.backend.name == "Latin Modern Roman"
    assert font.backend.path == path


def test_uchar_generates_other_tokens_and_space_tokens(parser):
    parser.readFrom("\\Uchar65 \\Uchar32 \\Uchar\"03B2")

    a = parser.token_expand()
    space = parser.token_expand()
    beta = parser.token_expand()

    assert (a.name, a.catcode) == ("A", CATCODE.OTHER)
    assert (space.name, space.catcode) == (" ", CATCODE.SPACE)
    assert (beta.name, beta.catcode) == ("\u03b2", CATCODE.OTHER)


def test_ucharcat_generates_requested_catcode(parser):
    parser.readFrom("\\Ucharcat65 11\\Ucharcat65 12")

    letter = parser.token_expand()
    other = parser.token_expand()

    assert (letter.name, letter.catcode) == ("A", CATCODE.LETTER)
    assert (other.name, other.catcode) == ("A", CATCODE.OTHER)


def test_ucharcat_generates_active_token_without_expanding_it(parser):
    parser.readFrom("65 13")
    parser.lookup("\\Ucharcat").expand(parser)

    active = parser.token()

    assert (active.name, active.catcode) == ("A", CATCODE.ACTIVE)
    assert active.entry is parser.equitable.entry("A")


def test_ucharcat_rejects_invalid_catcodes(parser):
    with pytest.raises(ValueError, match="Invalid code"):
        parser.parse("\\Ucharcat65 0")


def test_umathcode_accepts_xetex_three_integer_assignment(parser):
    parser.parse("\\Umathcode`A=7 1 65")

    assert parser.umathcode[ord("A")] == (((1 << 3) + 7) << 21) + 65


def test_umathcodenum_reads_and_writes_packed_mathcode(collector):
    packed = (((1 << 3) + 7) << 21) + 0x03B2

    collector.parse("\\Umathcodenum`A=%d \\number\\Umathcodenum`A" % packed)

    assert collector.getString().strip() == str(packed)


def test_umathchardef_defines_readable_unicode_math_char(collector):
    collector.parse("\\Umathchardef\\foo=7 1 \"03B2 \\number\\foo")

    assert collector.getString().strip() == str((((1 << 3) + 7) << 21) + 0x03B2)


def test_umathcharnumdef_defines_readable_packed_unicode_math_char(collector):
    packed = (((1 << 3) + 7) << 21) + 0x03B2

    collector.parse("\\Umathcharnumdef\\foo=%d \\number\\foo" % packed)

    assert collector.getString().strip() == str(packed)


def test_umathcharnumdef_accepts_umathcodenum_value(collector):
    packed = (((1 << 3) + 7) << 21) + 0x03B2

    collector.parse(
        "\\Umathcode`A=7 1 \"03B2 "
        "\\Umathcharnumdef\\foo=\\Umathcodenum`A "
        "\\number\\foo"
    )

    assert collector.getString().strip() == str(packed)


def test_umathchardef_appends_unicode_math_symbol(parser):
    parser.parse("\\Umathchardef\\foo=7 1 \"03B2 $\\foo")

    top = parser.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    atom = top[0]
    assert isinstance(atom, mmode.Atom)
    assert atom.atom_type == mmode.ATOM_TYPE.ORD
    assert atom.nucleus.fam == 1
    assert atom.nucleus.char == "\u03b2"


def test_umathchar_and_umathcharnum_append_unicode_math_symbols(parser):
    packed = (((1 << 3) + 7) << 21) + 0x03B2
    parser.parse("$\\Umathchar 7 1 \"03B2 \\Umathcharnum %d" % packed)

    top = parser.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 2
    assert [atom.nucleus.char for atom in top] == ["\u03b2", "\u03b2"]
    assert [atom.nucleus.fam for atom in top] == [1, 1]


def test_udelcode_accepts_xetex_family_and_glyph_assignment(parser):
    parser.parse("\\Udelcode`A=1 65")

    assert parser.udelcode[ord("A")] == ((0x200 + 1) << 21) + 65
