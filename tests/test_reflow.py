from pytex import box as bx
from pytex import glue
from pytex import mmode
from pytex import node as nd
from pytex import paragraph as pg
from pytex import reflow
from pytex.dimen import Dimen


class _ProbeTextRun(reflow.Element):
    font = None

    def __init__(self):
        super().__init__("text")
        self.spaces = []

    def setSpace(self, width, breakable=True):
        self.spaces.append(width)

    def setKern(self, kern):
        pass

    def setChar(self, char):
        pass


class _ProbeParagraph(reflow.Element):
    def __init__(self):
        super().__init__("paragraph")
        self.color = reflow.Color.black
        self.font = None
        self.text_run = _ProbeTextRun()
        self.inline_math_segment = 0
        self.inline_math_node = None

    def newTextRun(self, font, color):
        self.text_run = _ProbeTextRun()
        self.text_run.font = font
        self.append(self.text_run)
        return self.text_run

    def textRun(self, new=False):
        if new:
            return self.newTextRun(self.font, self.color)
        return self.text_run

    def setSpace(self, width, breakable=True):
        self.textRun().setSpace(width, breakable=breakable)

    def newLine(
        self,
        line_height=Dimen(),
        color=reflow.Color.black,
        force=False,
        spacing_before=Dimen(),
    ):
        line = _ProbeLine()
        self.append(line)
        return line

    def setJustify(self, justify):
        self.justify = justify

    def setFont(self, font):
        self.font = font


class _ProbeLine(_ProbeParagraph):
    pass


class _ProbeBlock(reflow.Element):
    def __init__(self):
        super().__init__("block")
        self.paragraphs = []

    def newParagraph(self, spacing_before=Dimen(), justify="left"):
        paragraph = _ProbeParagraph()
        paragraph.spacing_before = spacing_before
        paragraph.justify = justify
        self.paragraphs.append(paragraph)
        self.append(paragraph)
        return paragraph

    def newTable(self, xspacing=Dimen(), yspacing=Dimen()):
        table = _ProbeBlock()
        self.append(table)
        return table


class _ProbeDocument(reflow.Document):
    def __init__(self):
        super().__init__("document", "probe")
        self._body = _ProbeBlock()
        self.page_specs = []

    @property
    def body(self):
        return self._body

    @property
    def header(self):
        return _ProbeBlock()

    @property
    def footer(self):
        return _ProbeBlock()

    def newPage(self, page_spec):
        self.page_specs.append(page_spec)
        return page_spec

    def save(self):
        pass


class _ProbeBackend(reflow.Reflow):
    def __init__(self, parser):
        super().__init__(parser, paginate=True)
        self.inline_math = []
        self.specials = []

    def open(self):
        return _ProbeDocument()

    def typesetInlineMath(self, node, box, piece):
        self.inline_math.append((node, box, piece))


class _StackProbeBackend(_ProbeBackend):
    def __init__(self, parser):
        super().__init__(parser)
        self.hbox_stack_snapshots = []

    def typesetHBox(self, box, xspacing=Dimen(), yspacing=Dimen()):
        self.hbox_stack_snapshots.append(tuple(self.vbox_stack))
        return super().typesetHBox(box, xspacing=xspacing, yspacing=yspacing)


class _RegionTargetBackend(_ProbeBackend):
    def __init__(self, parser):
        super().__init__(parser)
        self.targets = []

    def setTarget(self, name):
        self.targets.append(name)


class _UnsupportedRegionAnnotationBackend(_ProbeBackend):
    support_annotation = True

    def newAnnotationBuilder(self, name=None, payload=None):
        raise AssertionError("unsupported-region annotation tried to create a line builder")

    def newFixedAnnotation(self, name, w, h):
        raise AssertionError("unsupported-region fixed annotation tried to create a rendered link")


def _empty_hbox(parser):
    hbox = bx.HBox(parser, None, 0)
    hbox.list = []
    return hbox.typeset(parser)


def _fixed_hbox(parser, items=None, width=0, height=0, depth=0, shifted=0):
    hbox = bx.HBox(parser, None, 0)
    hbox.list = list(items or [])
    hbox = hbox.typeset(parser)
    hbox.width = Dimen(width)
    hbox.height = Dimen(height)
    hbox.depth = Dimen(depth)
    hbox.to = hbox.width
    hbox.shifted = Dimen(shifted)
    return hbox


def _fixed_vbox(parser, items=None, width=0, height=0, depth=0, shifted=0):
    vbox = bx.VBox(parser, None, 0)
    vbox.list = list(items or [])
    vbox = vbox.typeset(parser)
    vbox.width = Dimen(width)
    vbox.height = Dimen(height)
    vbox.depth = Dimen(depth)
    vbox.to = vbox.height
    vbox.shifted = Dimen(shifted)
    return vbox


def _body_vbox(parser, items=None, width=80, height=60, depth=0):
    return _fixed_vbox(
        parser,
        [nd.Glue(glue.Glue(Dimen(4)), "\\topskip"), *(items or [])],
        width=width,
        height=height,
        depth=depth,
    )


class _ProbeWhatsit(nd.Node):
    node_type = nd.NODE_TYPE.WHATSIT

    def __init__(self, name):
        self.name = name

    def output(self, parser, backend):
        backend.specials.append(self.name)


def _pt(value):
    if isinstance(value, int):
        return float(Dimen(integer=value))
    return float(value)


def test_walk_page_collects_vmode_header_and_body(parser):
    backend = _ProbeBackend(parser)
    header = _fixed_hbox(parser, width=30, height=6, depth=2)
    body = _body_vbox(parser, width=100, height=80)
    page = _fixed_vbox(parser, [header, body], width=100, height=88)

    regions = backend.walkPage(page)

    assert regions.body is body
    assert regions.body_x == Dimen()
    assert regions.body_y == Dimen(8)
    assert [item.node for item in regions.header] == [header]
    assert regions.header[0].x == Dimen()
    assert regions.header[0].y == Dimen()
    assert regions.header_y == Dimen()
    assert regions.footer == []
    assert regions.left_margin == []
    assert regions.right_margin == []


def test_walk_page_classifies_vmode_and_hmode_siblings(parser):
    backend = _ProbeBackend(parser)
    header = _fixed_hbox(parser, width=40, height=7, depth=3, shifted=2)
    left = _fixed_hbox(parser, width=10, height=5, depth=1, shifted=4)
    body = _body_vbox(parser, width=100, height=80)
    right = _fixed_hbox(parser, width=20, height=4, depth=2, shifted=-3)
    footer = _fixed_hbox(parser, width=50, height=6, depth=2, shifted=5)
    row = _fixed_hbox(
        parser,
        [left, body, right],
        width=130,
        height=80,
        depth=0,
    )
    page = _fixed_vbox(parser, [header, row, footer], width=140, height=98)

    regions = backend.walkPage(page)

    assert regions.body is body
    assert regions.body_x == Dimen(10)
    assert regions.body_y == Dimen(10)
    assert [item.node for item in regions.header] == [header]
    assert regions.header[0].x == Dimen(2)
    assert regions.header[0].y == Dimen()
    assert regions.header_y == Dimen()
    assert [item.node for item in regions.left_margin] == [left]
    assert regions.left_margin[0].x == Dimen()
    assert regions.left_margin[0].y == Dimen(90 + 4)
    assert [item.node for item in regions.right_margin] == [right]
    assert regions.right_margin[0].x == Dimen()
    assert regions.right_margin[0].y == Dimen(90 - 3)
    assert [item.node for item in regions.footer] == [footer]
    assert regions.footer[0].x == Dimen(5)
    assert regions.footer[0].y == Dimen()
    assert regions.footer_y == Dimen(98)


def test_walk_page_uses_root_hlist_baseline_for_nested_body(parser):
    backend = _ProbeBackend(parser)
    body = _body_vbox(parser, width=40, height=30)
    page = _fixed_hbox(parser, [body], width=40, height=30, depth=5)

    regions = backend.walkPage(page)

    assert regions.body is body
    assert regions.body_y == Dimen()


def test_walk_page_region_order_is_fifo_for_nested_regions(parser):
    backend = _ProbeBackend(parser)
    outer_header = _fixed_hbox(parser, width=10, height=2, depth=1)
    inner_header = _fixed_hbox(parser, width=10, height=3, depth=1)
    body = _body_vbox(parser)
    inner_footer = _fixed_hbox(parser, width=10, height=4, depth=1)
    outer_footer = _fixed_hbox(parser, width=10, height=5, depth=1)
    inner = _fixed_vbox(
        parser,
        [inner_header, body, inner_footer],
        width=80,
        height=68,
    )
    page = _fixed_vbox(
        parser,
        [outer_header, inner, outer_footer],
        width=80,
        height=77,
    )

    regions = backend.walkPage(page)

    assert [item.node for item in regions.header] == [outer_header, inner_header]
    assert [item.node for item in regions.footer] == [inner_footer, outer_footer]


def test_shipout_scans_unsupported_region_whatsits_once(parser):
    backend = _ProbeBackend(parser)
    header_special = _ProbeWhatsit("header")
    left_special = _ProbeWhatsit("left")
    body_special = _ProbeWhatsit("body")
    right_special = _ProbeWhatsit("right")
    footer_special = _ProbeWhatsit("footer")
    header = _fixed_vbox(parser, [header_special], width=10, height=5)
    left = _fixed_hbox(parser, [left_special], width=10, height=0)
    body = _body_vbox(parser, [body_special], width=50, height=40)
    right = _fixed_hbox(parser, [right_special], width=10, height=0)
    footer = _fixed_vbox(parser, [footer_special], width=10, height=5)
    row = _fixed_hbox(parser, [left, body, right], width=70, height=40)
    page = _fixed_vbox(parser, [header, row, footer], width=70, height=50)

    backend.shipout(page)

    assert backend.specials == ["header", "left", "body", "right", "footer"]


def test_unsupported_region_scan_executes_pdf_specials_by_default(parser):
    backend = _RegionTargetBackend(parser)
    header = _fixed_vbox(
        parser,
        [
            nd.Special("pdf: dest (header.target)[@thispage/XYZ @xpos @ypos null]"),
            _ProbeWhatsit("ordinary"),
        ],
        width=10,
        height=5,
    )
    body = _body_vbox(parser, width=50, height=40)
    page = _fixed_vbox(parser, [header, body], width=50, height=45)

    backend.shipout(page)

    assert backend.targets == ["header.target"]
    assert backend.specials == ["ordinary"]


def test_unsupported_region_annotations_do_not_require_line_builder(parser):
    backend = _UnsupportedRegionAnnotationBackend(parser)
    header = _fixed_vbox(
        parser,
        [
            nd.Special("pdf: beginann <</Type/Annot/Subtype/Link/A<</S/GoTo/D(target.1)>>>>"),
            nd.Special("pdf: endann"),
            nd.Special("pdf: ann @note width 3pt height 4pt << /Type /Annot /Subtype /Text >>"),
        ],
        width=10,
        height=5,
    )
    body = _body_vbox(parser, width=50, height=40)
    page = _fixed_vbox(parser, [header, body], width=50, height=45)

    backend.shipout(page)


def test_typeset_line_packs_inline_math_with_line_glue_state(parser):
    backend = _ProbeBackend(parser)
    paragraph = _ProbeParagraph()
    owner = mmode.InlineMathNode(nodes=[])
    on = nd.MathShift(True)
    on.source = owner
    on.kern = Dimen()
    off = nd.MathShift(False)
    off.source = owner
    off.kern = Dimen()
    stretch = glue.Stretchness(1, 0)
    math_glue = nd.Glue(glue.Glue(0, stretch), None)
    after_glue = nd.Glue(glue.Glue(0, stretch), None)
    glue_state = {
        "num": int(Dimen(10)),
        "den": int(Dimen(2)),
        "order": 0,
        "shrink": False,
        "factor_sum": 0,
        "applied": 0,
    }

    with reflow.Builder(backend, paragraph):
        backend.paragraph = paragraph
        backend.typesetLine([on, math_glue, off, after_glue], glue_state=glue_state)

    assert len(backend.inline_math) == 1
    node, math_box, piece = backend.inline_math[0]
    assert node is owner
    assert piece == 1
    assert float(math_box.width) == 5
    assert tuple(math_box.glue_ratio) == (1, int(Dimen(10)), int(Dimen(2)))
    assert _pt(paragraph.text_run.spaces[-1]) == 5
    assert glue_state["factor_sum"] == int(Dimen(2))
    assert glue_state["applied"] == int(Dimen(10))


def test_inline_math_fragment_ignores_inactive_glue_order(parser):
    backend = _ProbeBackend(parser)
    paragraph = _ProbeParagraph()
    owner = mmode.InlineMathNode(nodes=[])
    on = nd.MathShift(True)
    on.source = owner
    on.kern = Dimen()
    off = nd.MathShift(False)
    off.source = owner
    off.kern = Dimen()
    math_glue = nd.Glue(glue.Glue(0, glue.Stretchness(1, 0)), None)
    glue_state = {
        "num": int(Dimen(10)),
        "den": int(Dimen(1)),
        "order": 1,
        "shrink": False,
        "factor_sum": 0,
        "applied": 0,
    }

    with reflow.Builder(backend, paragraph):
        backend.paragraph = paragraph
        backend.typesetLine([on, math_glue, off], glue_state=glue_state)

    _, math_box, _ = backend.inline_math[0]
    assert float(math_box.width) == 0
    assert tuple(math_box.glue_ratio) == (0, 0, 1)
    assert glue_state["factor_sum"] == 0
    assert glue_state["applied"] == 0


def test_typeset_vlist_passes_page_glue_state_to_paragraph(parser):
    backend = _ProbeBackend(parser)
    body = _ProbeBlock()
    owner = pg.Paragraph(parser, indent=False)
    line1 = _fixed_hbox(parser, width=50, height=8, depth=2)
    line1.source = owner
    interline = nd.Glue(
        glue.Glue(Dimen(12), shrink=glue.Stretchness(Dimen(12), 0)),
        "\\baselineskip",
    )
    interline.source = owner
    line2 = _fixed_hbox(parser, width=50, height=8, depth=2)
    line2.source = owner
    glue_state = {
        "num": -int(Dimen(6)),
        "den": int(Dimen(12)),
        "order": 0,
        "shrink": True,
        "factor_sum": 0,
        "applied": 0,
    }

    with reflow.Builder(backend, body):
        backend.typesetVList([line1, interline, line2], glue_state=glue_state, top_level=True)

    assert len(body.paragraphs) == 1
    assert glue_state["factor_sum"] == int(Dimen(12))
    assert glue_state["applied"] == -int(Dimen(6))


def test_vbox_stack_tracks_only_vertical_boxes(parser):
    backend = _StackProbeBackend(parser)
    hbox = _empty_hbox(parser)
    vbox = bx.VBox(parser, None, 0)
    vbox.list = [hbox]
    vbox = vbox.typeset(parser)
    body = _ProbeBlock()

    with reflow.Builder(backend, body):
        backend.typesetVBox(vbox, xspacing=Dimen(3), yspacing=Dimen(5))

    assert backend.vbox_stack == []
    assert len(backend.hbox_stack_snapshots) == 1
    (context,) = backend.hbox_stack_snapshots[0]
    assert context.box is vbox
    assert context.left == Dimen(3)
    assert context.top == Dimen(5)


def test_hbox_in_vertical_flow_lowers_to_paragraph(parser):
    backend = _ProbeBackend(parser)
    hbox = _empty_hbox(parser)
    body = _ProbeBlock()

    with reflow.Builder(backend, body):
        paragraph = backend.typesetHBox(hbox, yspacing=Dimen(7))

    assert paragraph in body.paragraphs
    assert body.nodes == [paragraph]
    assert paragraph.spacing_before == Dimen(7)
