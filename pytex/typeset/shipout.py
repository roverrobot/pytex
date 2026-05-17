"""Backend-neutral shipout walker and minimal IR hooks."""

import os
import re

from pytex import graphics
from pytex import node as nd
from pytex.dimen import Dimen, NEG_MAX_DIMEN, UNITS
from pytex.typeset.dvipdfm import DVIPDFmSpecialParser


_DIMEN_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))([A-Za-z]+)\s*$")


class Shipout:
    """
    Default shipout collector and backend-neutral page walker.

    The base class owns the traversal of shipped boxes and reduces them to a
    small backend IR consisting of page boundaries, positioning, font
    selection/definition, rules, characters, and specials. Concrete backends
    implement the IR methods below.
    """

    supported_graphic_formats = ()

    def __init__(self, parser, output=None):
        self.parser = parser
        self.output = output
        self.pages = []
        self.h = 0
        self.v = 0
        self._position_stack = []
        self._defined_fonts = set()
        self._dvipdfm = DVIPDFmSpecialParser(self)

    def shipout(self, box):
        self.open()
        self.pages.append(box)
        self.begin_page(box)
        h = int(self.parser.layout["hoffset"])
        v = int(self.parser.layout["voffset"])
        self._position_stack = []
        if box.node_type == nd.NODE_TYPE.VLIST:
            self.h = h
            self.v = v
            self.move_to(self.h, self.v)
            self._ship_vlist(box)
        else:
            self.h = h
            self.v = v + int(box.height)
            self.move_to(self.h, self.v)
            self._ship_hlist(box)       
        self.end_page(box)

    def _glue_state(self, box):
        ratio = getattr(box, "glue_ratio", None)
        if isinstance(ratio, tuple):
            sign, num, den = ratio
            sign = int(sign)
            num = int(num)
            den = int(den)
            if sign > 0 and num > 0 and den > 0:
                return {
                    "num": num,
                    "den": den,
                    "order": box.natural.stretch.order,
                    "shrink": False,
                    "factor_sum": 0,
                    "applied": 0,
                }
            if sign < 0 and num > 0 and den > 0:
                return {
                    "num": -num,
                    "den": den,
                    "order": box.natural.shrink.order,
                    "shrink": True,
                    "factor_sum": 0,
                    "applied": 0,
                }
            return None

        spread = int(getattr(box, "spread", Dimen()))
        if spread > 0 and int(box.natural.stretch.factor) != 0:
            return {
                "num": spread,
                "den": int(box.natural.stretch.factor),
                "order": box.natural.stretch.order,
                "shrink": False,
                "factor_sum": 0,
                "applied": 0,
            }
        if spread < 0 and int(box.natural.shrink.factor) != 0:
            return {
                "num": spread,
                "den": int(box.natural.shrink.factor),
                "order": box.natural.shrink.order,
                "shrink": True,
                "factor_sum": 0,
                "applied": 0,
            }
        return None

    def _glue_amount(self, node, box, state=None):
        amount = int(node.glue.dimen)
        if state is not None:
            part = node.glue.shrink if state["shrink"] else node.glue.stretch
            if part.order == state["order"]:
                state["factor_sum"] += int(part.factor)
                target = Dimen._round_div(state["factor_sum"] * state["num"], state["den"])
                amount += target - state["applied"]
                state["applied"] = target
        elif box is not None:
            ratio = box.glue_ratio
            if isinstance(ratio, tuple):
                ratio = type(box).ratioDimen(ratio)
            if ratio > 0:
                stretch = node.glue.stretch
                if stretch.order == box.natural.stretch.order:
                    amount += int(stretch.factor * ratio)
            elif ratio < 0:
                shrink = node.glue.shrink
                if shrink.order == box.natural.shrink.order:
                    amount += int(shrink.factor * ratio)
        return amount

    def _push_position(self):
        self._position_stack.append((self.h, self.v))
        if hasattr(self, "max_stack") and len(self._position_stack) > self.max_stack:
            self.max_stack = len(self._position_stack)

    def _pop_position(self):
        self.h, self.v = self._position_stack.pop()

    def _ensure_font(self, font):
        key = id(font)
        if key not in self._defined_fonts:
            self.define_font(font)
            self._defined_fonts.add(key)
        self.select_font(font)

    def _emit_whatsit(self, node):
        self.move_to(self.h, self.v)
        node.output(self.parser, self)

    def _ship_char(self, node):
        self.move_to(self.h, self.v)
        self._ensure_font(node.font)
        self.set_char(node)
        self.h += int(node.width)

    def _ship_rule(self, node, box, move):
        # Preserve the current DVI-compatible rule placement semantics. In
        # horizontal lists, the current point for a rule is lowered by its
        # depth; in vertical lists, the current point is used as-is.
        orig_h = self.h
        orig_v = self.v
        if box.node_type == nd.NODE_TYPE.HLIST:
            depth = int(box.depth) if int(node.depth) <= int(NEG_MAX_DIMEN) else int(node.depth)
            self.move_to(orig_h, orig_v + depth)
        else:
            self.move_to(orig_h, orig_v)
        self.set_rule(node, box, move)
        self.h = orig_h
        self.v = orig_v
        if box.node_type == nd.NODE_TYPE.HLIST:
            if move:
                self.h += int(node.width)
        else:
            if move:
                self.v += int(node.height)

    def _ship_box(self, box, parent):
        self._push_position()
        if parent.node_type == nd.NODE_TYPE.HLIST:
            if box.node_type == nd.NODE_TYPE.HLIST:
                self.v += int(box.shifted)
                self.move_to(self.h, self.v)
                self._ship_hlist(box)
            else:
                self.v += int(box.shifted) - int(box.height)
                self.move_to(self.h, self.v)
                self._ship_vlist(box)
            self._pop_position()
            self.h += int(box.width)
        else:
            if box.node_type == nd.NODE_TYPE.HLIST:
                self.h += int(box.shifted)
                self.v += int(box.height)
                self.move_to(self.h, self.v)
                self._ship_hlist(box)
            else:
                self.h += int(box.shifted)
                self.move_to(self.h, self.v)
                self._ship_vlist(box)
            self._pop_position()
            self.v += int(box.height + box.depth)

    def _ship_hlist(self, box):
        items = getattr(box, "list", None)
        if items is None:
            return
        glue_state = self._glue_state(box)
        for node in items:
            node_type = node.node_type
            if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                self._ship_char(node)
            elif node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                self._ship_box(node, box)
            elif node_type == nd.NODE_TYPE.RULE:
                self._ship_rule(node, box, True)
            elif node_type == nd.NODE_TYPE.GLUE:
                assert getattr(box, "glue_ratio", None) is not None, "discretionary node contains glue"
                self.h += self._glue_amount(node, box, glue_state)
            elif node_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.MATH):
                self.h += int(node.kern)
            elif node_type == nd.NODE_TYPE.DISC:
                self._ship_hlist(node)
            elif node_type == nd.NODE_TYPE.WHATSIT:
                self._emit_whatsit(node)

    def _ship_vlist(self, box):
        items = getattr(box, "list", None)
        if items is None:
            return
        glue_state = self._glue_state(box)
        for node in items:
            node_type = node.node_type
            if node_type == nd.NODE_TYPE.GLUE:
                self.v += self._glue_amount(node, box, glue_state)
            elif node_type == nd.NODE_TYPE.KERN:
                self.v += int(node.kern)
            elif node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                self._ship_box(node, box)
            elif node_type == nd.NODE_TYPE.RULE:
                self._ship_rule(node, box, False)
            elif node_type == nd.NODE_TYPE.WHATSIT:
                self._emit_whatsit(node)

    def begin_page(self, box):
        pass

    def end_page(self, box):
        pass

    def define_font(self, font):
        pass

    def select_font(self, font):
        pass

    def move_to(self, h, v):
        pass

    def set_char(self, node):
        pass

    def set_rule(self, node, box, move):
        pass

    def special(self, text):
        if not self._dvipdfm.emit(text):
            self.rawSpecial(text)

    def rawSpecial(self, text):
        pass

    def currentTransformScale(self):
        return (1.0, 1.0)

    def setColor(self, mode, space=None, values=None):
        pass

    def beginTransform(self):
        pass

    def scaleTransform(self, sx, sy):
        pass

    def rotateTransform(self, angle):
        pass

    def translateTransform(self, dx, dy):
        pass

    def endTransform(self):
        pass

    def setTarget(self, name):
        pass

    def annotate(self, kind, name=None, dimensions=None, payload=None):
        pass

    def xObject(self, kind, name=None, options=None, source=None):
        pass

    def graphic(self, spec):
        pass

    def _graphic_source_path(self, source):
        if not source:
            return None
        if self.parser.resolver.resolveInMemory(source) is not None:
            return None
        try:
            path = self.parser.resolver._sourcePath(source)
        except ValueError:
            return None
        if not os.path.exists(path):
            return None
        return path

    @staticmethod
    def _graphic_dimen_option(value):
        if value is None:
            return None
        if isinstance(value, Dimen):
            return Dimen(value)
        match = _DIMEN_RE.match(str(value))
        if match is None:
            return Dimen(value)
        amount = float(match.group(1))
        unit = match.group(2).lower()
        if unit not in UNITS:
            raise ValueError(f"unsupported special unit {unit}")
        num, den = UNITS[unit]
        scaled = round(amount * 1000000)
        return Dimen(integer=Dimen._trunc_div(scaled * num * Dimen.scale, den * 1000000))

    @staticmethod
    def _graphic_bp_dimen(value):
        num, den = UNITS["bp"]
        scaled = round(float(value) * 1000000)
        return Dimen(integer=Dimen._trunc_div(scaled * num * Dimen.scale, den * 1000000))

    @staticmethod
    def _graphic_bbox(options):
        bbox = options.get("bbox")
        if bbox is None:
            return None
        try:
            llx, lly, urx, ury = (float(v) for v in bbox)
        except (TypeError, ValueError):
            return None
        if llx == lly == urx == ury == 0:
            return None
        return llx, lly, urx, ury

    @staticmethod
    def _graphic_image_size(path):
        try:
            from PIL import Image

            with Image.open(path) as image:
                width, height = image.size
        except Exception:
            return None
        return Dimen(width), Dimen(height)

    @staticmethod
    def _graphic_pdf_page_box(path, page_number, pagebox):
        try:
            from pypdf import PdfReader

            reader = PdfReader(path)
            page = reader.pages[page_number - 1]
            box = getattr(page, pagebox, page.cropbox)
            llx, lly, urx, ury = tuple(map(float, box))
        except Exception:
            return None
        return Shipout._graphic_bp_dimen(urx - llx), Shipout._graphic_bp_dimen(ury - lly)

    def _graphic_natural_size(self, spec, path, options):
        bbox = self._graphic_bbox(options)
        if bbox is not None:
            llx, lly, urx, ury = bbox
            return self._graphic_bp_dimen(urx - llx), self._graphic_bp_dimen(ury - lly)
        if spec.kind == "epdf" and path is not None:
            page_number = int(options.get("page", "1"))
            pagebox = str(options.get("pagebox", "cropbox")).lower()
            return self._graphic_pdf_page_box(path, page_number, pagebox)
        if spec.kind == "image" and path is not None:
            return self._graphic_image_size(path)
        return None

    def _graphic_target_size(self, spec, path, options):
        natural = self._graphic_natural_size(spec, path, options)
        bbox = self._graphic_bbox(options)
        ratio = None
        if bbox is not None:
            llx, lly, urx, ury = bbox
            ratio = (urx - llx, ury - lly)
        width = self._graphic_dimen_option(options.get("width"))
        height = self._graphic_dimen_option(options.get("height"))
        if width is None and height is None:
            if natural is not None:
                width, height = natural
        elif width is None:
            if ratio is not None and ratio[1] != 0:
                width = height * (ratio[0] / ratio[1])
            elif natural is not None and int(natural[1]) != 0:
                width = natural[0] * (float(height) / float(natural[1]))
        elif height is None:
            if ratio is not None and ratio[0] != 0:
                height = width * (ratio[1] / ratio[0])
            elif natural is not None and int(natural[0]) != 0:
                height = natural[1] * (float(width) / float(natural[0]))

        scale = float(options.get("scale", "1"))
        xscale = float(options.get("xscale", "1"))
        yscale = float(options.get("yscale", "1"))
        tx, ty = self.currentTransformScale()
        if width is not None:
            width *= scale * xscale * tx
        if height is not None:
            height *= scale * yscale * ty
        return width, height

    def graphicRequestFromSpec(self, spec):
        if spec.kind not in ("epdf", "image") or not spec.source:
            return None
        options = spec.option_map
        path = self._graphic_source_path(spec.source)
        source_format = spec.format or ("pdf" if spec.kind == "epdf" else graphics.graphic_format(spec.source))
        if source_format is None:
            return None
        page = int(options.get("page", "1"))
        pagebox = str(options.get("pagebox", "cropbox")).lower()
        width, height = self._graphic_target_size(spec, path, options)
        depth = self._graphic_dimen_option(options.get("depth")) or Dimen()
        _tx, ty = self.currentTransformScale()
        if int(depth) != 0:
            depth *= float(options.get("scale", "1")) * float(options.get("yscale", "1")) * ty
        return graphics.GraphicRequest(
            source=spec.source,
            path=path,
            source_format=source_format,
            kind=spec.kind,
            page=page,
            pagebox=pagebox,
            bbox=options.get("bbox"),
            width=width,
            height=height,
            depth=depth,
            rotate=float(options.get("rotate", "0")),
        )

    def prepareGraphicAsset(self, request):
        supported = tuple(format.lower() for format in self.supported_graphic_formats)
        if request.source_format.lower() in supported:
            return graphics.GraphicAsset(
                format=request.source_format.lower(),
                path=request.path,
                width=request.width,
                height=request.height,
                depth=request.depth,
            )
        for target_format in supported:
            try:
                asset = graphics.convert_graphic(request, target_format)
            except RuntimeError:
                asset = None
            if asset is not None:
                return asset
        return None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def open(self):
        pass

    def close(self):
        pass
