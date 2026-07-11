"""Backend-neutral graphics IR shared by shipout backends."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Optional, Union

from pytex.dimen import Dimen


def graphic_format(filename):
    suffix = os.path.splitext(filename)[1].lower().lstrip(".")
    if suffix == "jpeg":
        return "jpg"
    return suffix or None


@dataclass(frozen=True)
class GraphicSpec:
    kind: str
    source: str
    name: str = None
    options: tuple = field(default_factory=tuple)
    format: str = None

    @classmethod
    def from_dvipdfm(cls, kind, name=None, options=None, source=None):
        source = "" if source is None else source
        format = "pdf" if kind == "epdf" else None
        if kind == "image":
            format = graphic_format(source)
        return cls(
            kind=kind,
            name=name,
            source=source,
            options=tuple(options or ()),
            format=format,
        )

    @property
    def option_map(self):
        return {key: value for key, value in self.options}


@dataclass
class GraphicRequest:
    source: str
    path: Optional[str]
    source_format: str
    kind: str = "image"
    page: int = 1
    pagebox: str = "cropbox"
    bbox: Optional[tuple] = None
    width: Optional[Dimen] = None
    height: Optional[Dimen] = None
    depth: Dimen = field(default_factory=Dimen)
    rotate: float = 0.0


@dataclass
class GraphicAsset:
    format: str
    path: Optional[str] = None
    data: Optional[Union[bytes, str]] = None
    width: Optional[Dimen] = None
    height: Optional[Dimen] = None
    depth: Dimen = field(default_factory=Dimen)


_CONVERTERS = {}


def register_converter(source_format, target_format, converter):
    _CONVERTERS[(source_format.lower(), target_format.lower())] = converter


def get_converter(source_format, target_format):
    return _CONVERTERS.get((source_format.lower(), target_format.lower()))


def convert_graphic(request, target_format):
    converter = get_converter(request.source_format, target_format)
    if converter is None:
        return None
    return converter.convert(request)


class GraphicConverter:
    source_format = None
    target_format = None

    def convert(self, request: GraphicRequest) -> GraphicAsset:
        raise NotImplementedError


class PDFToSVGConverter(GraphicConverter):
    source_format = "pdf"
    target_format = "svg"

    def convert(self, request: GraphicRequest) -> GraphicAsset:
        if request.path is None:
            return None
        if request.page < 1:
            return None
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("PDF-to-SVG conversion requires PyMuPDF") from exc

        try:
            doc = fitz.open(request.path)
        except Exception as exc:
            raise RuntimeError(f"could not open PDF graphic {request.path}") from exc
        try:
            try:
                page = doc[request.page - 1]
            except IndexError as exc:
                raise RuntimeError(
                    f"PDF graphic {request.path} has no page {request.page}"
                ) from exc
            try:
                clip = self._clip_rect(fitz, page, request)
                svg = self._page_svg(page, clip)
            except Exception as exc:
                raise RuntimeError(f"could not convert PDF graphic {request.path} to SVG") from exc
        finally:
            doc.close()
        return GraphicAsset(
            format="svg",
            data=svg,
            width=request.width,
            height=request.height,
            depth=request.depth,
        )

    @staticmethod
    def _page_svg(page, clip=None):
        if clip is None:
            return page.get_svg_image()
        old_cropbox = page.cropbox
        try:
            try:
                page.set_cropbox(clip)
            except ValueError:
                # Some PDF boxes reported by PyMuPDF, or dvipdfmx bbox values,
                # may not be accepted as a CropBox for this page. In that case,
                # fall back to the full-page SVG rather than failing graphic
                # conversion completely.
                return page.get_svg_image()
            return page.get_svg_image()
        finally:
            try:
                page.set_cropbox(old_cropbox)
            except ValueError:
                pass

    def _clip_rect(self, fitz, page, request):
        if request.bbox is not None:
            rect = self._bbox_rect(fitz, page, request.bbox)
        else:
            pagebox = (request.pagebox or "cropbox").lower()
            rect = self._pagebox_rect(fitz, page, pagebox)
        rect = self._valid_crop_rect(fitz, page, rect)
        if rect is None:
            return None
        page_rect = fitz.Rect(page.cropbox)
        if self._same_rect(rect, page_rect):
            return None
        return rect

    @staticmethod
    def _bbox_rect(fitz, page, bbox):
        """Convert a PDF-space bbox to a PyMuPDF page-space rectangle.

        dvipdfmx/XeTeX bbox values use PDF coordinates with the origin at the
        lower-left corner. PyMuPDF page rectangles use coordinates relative to the
        page's top-left corner. Passing the PDF bbox directly to fitz.Rect
        can leave a large blank area in the converted SVG.
        """
        if len(bbox) != 4:
            return None
        try:
            llx, lly, urx, ury = (float(value) for value in bbox)
        except (TypeError, ValueError):
            return None
        media = fitz.Rect(page.mediabox)
        page_height = media.height
        x0 = llx - media.x0
        x1 = urx - media.x0
        y0 = page_height - (ury - media.y0)
        y1 = page_height - (lly - media.y0)
        return fitz.Rect(x0, y0, x1, y1)

    @staticmethod
    def _pagebox_rect(fitz, page, pagebox):
        attr = {
            "media": "mediabox",
            "mediabox": "mediabox",
            "crop": "cropbox",
            "cropbox": "cropbox",
            "bleed": "bleedbox",
            "bleedbox": "bleedbox",
            "trim": "trimbox",
            "trimbox": "trimbox",
            "art": "artbox",
            "artbox": "artbox",
        }.get(pagebox)
        if attr is None:
            return None
        rect = getattr(page, attr, None)
        if rect is None:
            return None
        return fitz.Rect(rect)

    @staticmethod
    def _same_rect(a, b, tol=1e-6):
        return (
            abs(a.x0 - b.x0) <= tol
            and abs(a.y0 - b.y0) <= tol
            and abs(a.x1 - b.x1) <= tol
            and abs(a.y1 - b.y1) <= tol
        )

    @staticmethod
    def _valid_crop_rect(fitz, page, rect):
        if rect is None:
            return None
        try:
            rect = fitz.Rect(rect)
            rect.normalize()
            media = fitz.Rect(page.mediabox)
            media.normalize()
            rect = rect & media
        except Exception:
            return None
        if rect.is_empty or rect.is_infinite:
            return None
        if rect.width <= 0 or rect.height <= 0:
            return None
        return rect


class EPSToSVGConverter(GraphicConverter):
    source_format = "eps"
    target_format = "svg"

    def __init__(self, pdf_converter=None):
        self.pdf_converter = pdf_converter or PDFToSVGConverter()

    def convert(self, request: GraphicRequest) -> GraphicAsset:
        if request.path is None:
            raise RuntimeError(f"EPS graphic {request.source} is not filesystem-backed")

        epstopdf = shutil.which("epstopdf")
        ghostscript = shutil.which("gs") if epstopdf is None else None
        if epstopdf is None and ghostscript is None:
            raise RuntimeError(
                f"could not convert EPS graphic {request.path}: "
                "neither epstopdf nor Ghostscript (gs) is installed"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            eps_path = Path(tmpdir) / "graphic.eps"
            pdf_path = Path(tmpdir) / "graphic.pdf"
            try:
                shutil.copyfile(request.path, eps_path)
            except OSError as exc:
                raise RuntimeError(f"could not read EPS graphic {request.path}: {exc}") from exc
            if epstopdf is not None:
                command = [epstopdf, "--restricted", "--outfile=graphic.pdf", "graphic.eps"]
                converter_name = "epstopdf"
            else:
                command = [
                    ghostscript,
                    "-dSAFER",
                    "-dBATCH",
                    "-dNOPAUSE",
                    "-sDEVICE=pdfwrite",
                    "-dEPSCrop",
                    "-sOutputFile=graphic.pdf",
                    "graphic.eps",
                ]
                converter_name = "Ghostscript"
            self._run(command, converter_name, request.path, cwd=tmpdir)
            if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
                raise RuntimeError(
                    f"{converter_name} did not produce a PDF for EPS graphic {request.path}"
                )
            pdf_request = GraphicRequest(
                source=request.source,
                path=os.fspath(pdf_path),
                source_format="pdf",
                kind="epdf",
                page=1,
                pagebox="cropbox",
                bbox=None,
                width=request.width,
                height=request.height,
                depth=request.depth,
                rotate=request.rotate,
            )
            return self.pdf_converter.convert(pdf_request)

    @staticmethod
    def _run(command, converter_name, source, cwd=None):
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                cwd=cwd,
            )
        except OSError as exc:
            raise RuntimeError(
                f"could not run {converter_name} for EPS graphic {source}: {exc}"
            ) from exc
        if result.returncode == 0:
            return
        detail = (result.stderr or result.stdout or "").strip()
        message = f"{converter_name} failed to convert EPS graphic {source}"
        if detail:
            message += f": {detail}"
        raise RuntimeError(message)


register_converter("pdf", "svg", PDFToSVGConverter())
register_converter("eps", "svg", EPSToSVGConverter())
