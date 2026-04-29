import pytest

from pytex.token import CATCODE


@pytest.fixture(scope="module", autouse=True)
def _enable_xetex_module():
    from pytex import xetex  # register xetex module for this test file


def test_xetex_version_primitives_expand_like_engine_identity(collector):
    collector.parse("\\number\\XeTeXversion\\XeTeXrevision")
    assert collector.getString().strip() == "0.999995"


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
