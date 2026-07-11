"""Command-line entry point for ``python -m pytex``."""

from argparse import ArgumentParser
import cProfile
import importlib
import os
import pstats
import sys
import types

from pytex.parser import Parser

# Register the resolver, e-TeX features, and OpenType support before Parser()
# populates itself from the module registry.
from pytex import etex  # noqa: F401,E402
from pytex import opentype  # noqa: F401,E402
from pytex import texlive  # noqa: F401,E402


BACKENDS = ("dvi", "xdv", "pdf", "html-reflow", "docx", "svg")
ENGINES = ("xetex", "pdftex")
PROFILE_SORT_KEYS = (
    "calls",
    "cumulative",
    "filename",
    "line",
    "module",
    "name",
    "nfl",
    "pcalls",
    "stdname",
    "time",
)


def argument_parser():
    parser = ArgumentParser(prog="python -m pytex")
    parser.add_argument(
        "-f",
        "--format",
        default="initex",
        help=(
            "load the format FMT. If FMT is initex, dump the format provided "
            "by the input file"
        ),
        metavar="FMT",
    )
    parser.add_argument(
        "-p",
        "--profile",
        action="store_true",
        help="profile the parser",
    )
    parser.add_argument(
        "-e",
        "--engine",
        default="xetex",
        choices=ENGINES,
        help="TeX engine compatibility layer used to build/load the format",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="pdf",
        choices=BACKENDS,
        help=(
            "shipout output format. Relative output paths are derived from "
            "the jobname in the project directory"
        ),
    )
    parser.add_argument(
        "-s",
        "--sort",
        default=None,
        choices=PROFILE_SORT_KEYS,
        help="profile sorting key (default: time)",
    )
    parser.add_argument(
        "--project-dir",
        default=os.getcwd(),
        help="project directory for source reads (default: current directory)",
    )
    parser.add_argument("file")
    return parser


def engine_format_name(name, engine):
    suffix = f"-{engine}"
    return name if name.endswith(suffix) else f"{name}{suffix}"


def main(argv=None):
    args = argument_parser().parse_args(argv)
    if args.sort is not None and not args.profile:
        print("Warning: --sort/-s has no effect without --profile", file=sys.stderr)

    importlib.import_module(f"pytex.{args.engine}")
    if args.format != "initex":
        importlib.import_module(f"pytex.{args.output.replace('-', '_')}")

    parser = Parser(project_dir=args.project_dir)
    parser.resolver.format = args.format

    def dumper(parser, data):
        filename = engine_format_name(parser.resolver.format, args.engine) + ".pfmt"
        with open(filename, "wb") as format_file:
            format_file.write(data)

    parser.dumper = types.MethodType(dumper, parser)
    if args.profile:
        parser.console = open(os.devnull, "w")

    source = args.file
    base = os.path.basename(source)
    jobname, extension = os.path.splitext(base)

    if args.format == "initex":
        if extension == "" and source != "plain":
            source += ".ini"
        parser.resolver.format = jobname
        format_name = engine_format_name(parser.resolver.format, args.engine)
        print(
            f"the format is initex. Will dump the format "
            f"{parser.resolver.format} to {format_name}.pfmt",
            file=parser.console,
        )
    else:
        if args.output == "svg":
            from pytex import svg

            parser.shipout = svg.SVGShipoutBackend(parser, jobname)
        parser.resolver.format = args.format
        format_file = parser.resolver.openIn(
            engine_format_name(parser.resolver.format, args.engine),
            "dump",
        )
        if format_file is None:
            raise ValueError(f"cannot find format {parser.resolver.format}")
        parser.load(format_file)
        format_file.close()

    input_file = parser.resolver.openIn(source, "source")
    if input_file is None:
        raise ValueError(f"cannot find {source}")

    def run_document():
        if args.format != "initex" and parser.equitable["\\DocumentMetadata"] is not None:
            latex_backend = "xetex" if args.engine == "xetex" else "dvipdfmx"
            metadata = f"\\DocumentMetadata{{backend={latex_backend}}}\\relax\n"
            parser.readFrom(input_file, jobname)
            parser.parse(metadata, jobname=jobname)
        else:
            parser.parse(input_file, jobname=jobname)
        input_file.close()
        if args.format != "initex":
            parser.end()

    if args.profile:
        profile_sort = args.sort if args.sort is not None else "time"
        profiler = cProfile.Profile()
        profiler.enable()
        run_document()
        profiler.disable()
        stats = pstats.Stats(profiler)
        stats.sort_stats(profile_sort)
        stats.print_stats()
        parser.console.close()
        parser.close()
        return 0

    run_document()
    if args.format == "initex":
        parser.dumper(parser.dump())
    parser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
