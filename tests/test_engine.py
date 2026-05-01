from pytex import expandable
from pytex import token
from pytex.integer import FixedInteger


class StringCommand(token.Command):
    def __init__(self, value):
        self.toks = expandable.toToks(value)

    def expand(self, parser):
        parser.input.pushTokenList(self.toks)


def test_register_engine_replaces_previous_engine_commands(collector):
    pdf_commands = {
        "pdftexversion": FixedInteger(140),
        "pdftexrevision": StringCommand(".24"),
    }
    xetex_commands = {
        "XeTeXversion": FixedInteger(0),
        "XeTeXrevision": StringCommand(".999995"),
    }

    collector.registerEngine("pdftex", pdf_commands)
    collector.parse(r"\number\pdftexversion\pdftexrevision")
    assert collector.engine == ("pdftex", pdf_commands)
    assert collector.getString().strip() == "140.24"

    collector.registerEngine("xetex", xetex_commands)
    assert collector.engine == ("xetex", xetex_commands)
    assert collector.builtin.get(r"\pdftexversion") is None
    assert collector.builtin.get(r"\pdftexrevision") is None
    assert collector.equitable[r"\pdftexversion"] is None
    assert collector.equitable[r"\pdftexrevision"] is None

    collector.parse(r"\number\XeTeXversion\XeTeXrevision")
    assert collector.getString().strip() == "0.999995"
