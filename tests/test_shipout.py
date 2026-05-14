from pytex.typeset.shipout import Shipout
from pytex import node as nd
from pytex.dimen import Dimen


class _CaptureShipout(Shipout):
    def __init__(self, parser):
        super().__init__(parser)
        self.calls = []

    def rawSpecial(self, text):
        self.calls.append(("raw", text))

    def setColor(self, mode, space=None, values=None):
        self.calls.append(("color", mode, space, values))

    def setTarget(self, name):
        self.calls.append(("target", name))

    def annotate(self, kind, name=None, dimensions=None, payload=None):
        self.calls.append(("annotate", kind, name, dimensions, payload))

    def xObject(self, kind, name=None, options=None, source=None):
        self.calls.append(("xobject", kind, name, options, source))


class _FakeHBox:
    node_type = nd.NODE_TYPE.HLIST
    height = Dimen(7)
    depth = Dimen(2)
    list = []


class _FakeChar:
    node_type = nd.NODE_TYPE.CHAR
    width = Dimen(3)
    font = object()


def test_top_level_hbox_shipout_starts_at_baseline(parser):
    class BaselineShipout(_CaptureShipout):
        def move_to(self, h, v):
            self.calls.append(("move", Dimen(integer=h), Dimen(integer=v)))

        def set_char(self, node):
            self.calls.append(("char", Dimen(integer=self.h), Dimen(integer=self.v)))

    parser.layout["hoffset"] = Dimen(5)
    parser.layout["voffset"] = Dimen(11)
    hbox = _FakeHBox()
    hbox.list = [_FakeChar()]
    shipout = BaselineShipout(parser)

    shipout.shipout(hbox)

    assert ("char", Dimen(5), Dimen(18)) in shipout.calls


def test_shipout_parses_dvipdfm_color_special(parser):
    shipout = _CaptureShipout(parser)
    shipout.special(" pdf: bc [ 1 0 0 ] ")
    assert shipout.calls == [("color", "push", "rgb", ("1", "0", "0"))]


def test_shipout_parses_dvipdfm_annotation_special(parser):
    shipout = _CaptureShipout(parser)
    shipout.special("pdf: ann @note width 3in height 36pt << /Type /Annot /Subtype /Text >>")
    assert shipout.calls == [
        (
            "annotate",
            "fixed",
            "@note",
            [("width", "3in"), ("height", "36pt")],
            "<< /Type /Annot /Subtype /Text >>",
        )
    ]


def test_shipout_parses_dvipdfm_destination_special(parser):
    shipout = _CaptureShipout(parser)
    shipout.special("pdf: dest (target.1)[@thispage/XYZ @xpos @ypos null]")
    assert shipout.calls == [("target", "target.1")]


def test_shipout_parses_dvipdfm_xobject_special(parser):
    shipout = _CaptureShipout(parser)
    shipout.special("pdf: image @fig width 4in rotate 45 (figure.png)")
    assert shipout.calls == [
        (
            "xobject",
            "image",
            "@fig",
            [("width", "4in"), ("rotate", "45")],
            "(figure.png)",
        )
    ]


def test_shipout_keeps_unknown_specials_raw(parser):
    shipout = _CaptureShipout(parser)
    shipout.special("color push rgb 1 0 0")
    assert shipout.calls == [("raw", "color push rgb 1 0 0")]
