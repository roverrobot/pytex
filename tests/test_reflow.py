from pytex import glue
from pytex import mmode
from pytex import node as nd
from pytex import reflow
from pytex.dimen import Dimen


class _ProbeTextRun(reflow.Element):
    font = None

    def __init__(self):
        super().__init__("text")
        self.spaces = []

    def setSpace(self, width, breakable=True):
        self.spaces.append(width)

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
        return self.text_run

    def setFont(self, font):
        self.font = font


class _ProbeBackend(reflow.Reflow):
    def __init__(self, parser):
        super().__init__(parser, paginate=True)
        self.inline_math = []

    def typesetInlineMath(self, node, box, piece):
        self.inline_math.append((node, box, piece))


def _pt(value):
    if isinstance(value, int):
        return float(Dimen(integer=value))
    return float(value)


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
