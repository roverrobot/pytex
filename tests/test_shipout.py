from pytex.typeset.shipout import Shipout


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
