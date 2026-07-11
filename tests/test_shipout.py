import pytest

from pytex.typeset.shipout import Shipout
from pytex import graphics
from pytex import node as nd
from pytex.dimen import Dimen
from pytex.graphics import GraphicSpec


class _CaptureShipout(Shipout):
    def __init__(self, parser):
        super().__init__(parser)
        self.calls = []

    def rawSpecial(self, text):
        self.calls.append(("raw", text))

    def setColor(self, mode, space=None, values=None):
        self.calls.append(("color", mode, space, values))

    def beginTransform(self):
        self.calls.append(("begin-transform",))

    def scaleTransform(self, sx, sy):
        self.calls.append(("scale-transform", sx, sy))

    def endTransform(self):
        self.calls.append(("end-transform",))

    def setTarget(self, name):
        self.calls.append(("target", name))

    def annotate(self, kind, name=None, dimensions=None, payload=None):
        self.calls.append(("annotate", kind, name, dimensions, payload))

    def xObject(self, kind, name=None, options=None, source=None):
        self.calls.append(("xobject", kind, name, options, source))

    def graphic(self, spec):
        self.calls.append(("graphic", spec))


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


def test_shipout_parses_xdvipdfmx_scale_transform_specials(parser):
    shipout = _CaptureShipout(parser)
    shipout.special("pdf:btrans")
    shipout.special("x:scale 0.5 0.25")
    shipout.special("pdf:etrans")

    assert shipout.calls == [
        ("begin-transform",),
        ("scale-transform", "0.5", "0.25"),
        ("end-transform",),
    ]


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


def test_shipout_parses_dvipdfm_graphic_special(parser):
    shipout = _CaptureShipout(parser)
    shipout.special("pdf: image @fig width 4in rotate 45 (figure.png)")
    spec = GraphicSpec(
        kind="image",
        name="@fig",
        options=(("width", "4in"), ("rotate", "45")),
        source="figure.png",
        format="png",
    )
    assert shipout.calls == [
        (
            "graphic",
            spec,
        )
    ]


def test_shipout_parses_dvips_eps_graphic_special(parser):
    shipout = _CaptureShipout(parser)
    shipout.special(
        'PSfile="figure with spaces.eps" llx=0 lly=0 urx=390 ury=451 '
        'rwi=3240 rhi=3746 angle=90 clip'
    )

    assert shipout.calls == [
        (
            "graphic",
            GraphicSpec(
                kind="image",
                source="figure with spaces.eps",
                options=(
                    ("bbox", ("0", "0", "390", "451")),
                    ("width", "324bp"),
                    ("height", "374.6bp"),
                    ("rotate", "90"),
                    ("clip", "true"),
                ),
                format="eps",
            ),
        )
    ]


def test_shipout_prepares_graphic_asset_using_supported_format_order(parser, monkeypatch):
    class FakeConverter:
        def convert(self, request):
            return graphics.GraphicAsset(
                format="svg",
                data="<svg/>",
                width=request.width,
                height=request.height,
                depth=request.depth,
            )

    class GraphicShipout(_CaptureShipout):
        supported_graphic_formats = ("svg", "png")

    monkeypatch.setitem(graphics._CONVERTERS, ("pdf", "svg"), FakeConverter())
    shipout = GraphicShipout(parser)
    request = graphics.GraphicRequest(
        source="figure.pdf",
        path=None,
        source_format="pdf",
        width=Dimen(72),
        height=Dimen(36),
    )

    asset = shipout.prepareGraphicAsset(request)

    assert asset.format == "svg"
    assert asset.data == "<svg/>"
    assert asset.width == Dimen(72)
    assert asset.height == Dimen(36)


def test_shipout_prepares_directly_supported_graphic_without_conversion(parser):
    class GraphicShipout(_CaptureShipout):
        supported_graphic_formats = ("svg", "png")

    request = graphics.GraphicRequest(
        source="figure.png",
        path="/tmp/figure.png",
        source_format="png",
        width=Dimen(72),
        height=Dimen(36),
    )

    asset = GraphicShipout(parser).prepareGraphicAsset(request)

    assert asset.format == "png"
    assert asset.path == "/tmp/figure.png"
    assert asset.width == Dimen(72)
    assert asset.height == Dimen(36)


def test_shipout_propagates_graphic_conversion_failure(parser, monkeypatch):
    class FailingConverter:
        def convert(self, request):
            raise RuntimeError("EPS conversion unavailable")

    class GraphicShipout(_CaptureShipout):
        supported_graphic_formats = ("svg",)

    monkeypatch.setitem(graphics._CONVERTERS, ("eps", "svg"), FailingConverter())
    request = graphics.GraphicRequest(
        source="figure.eps",
        path="/tmp/figure.eps",
        source_format="eps",
        width=Dimen(72),
        height=Dimen(36),
    )

    with pytest.raises(RuntimeError, match="EPS conversion unavailable"):
        GraphicShipout(parser).prepareGraphicAsset(request)


def test_shipout_keeps_unknown_specials_raw(parser):
    shipout = _CaptureShipout(parser)
    shipout.special("color push rgb 1 0 0")
    assert shipout.calls == [("raw", "color push rgb 1 0 0")]
