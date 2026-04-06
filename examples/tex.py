from pathlib import Path
import sys
path = str(Path(Path(__file__).parent.absolute()).parent.absolute())
sys.path.insert(0, path)
import cProfile
import pstats
from pytex.parser import Parser
# load the texlive module to resolve files in the texlive tree
from pytex import texlive
from pytex import etex
# latex would require pdftex
from pytex import pdftex
from pytex import opentype

from argparse import ArgumentParser
import os
import types

backends = ["dvi", "pdf"]
html_reflow_backend = None

argparser = ArgumentParser()
argparser.add_argument("-f", "--format", default="initex",
                    help="load the format FMT. If FMT is initex, it dumps a format file. The format is provided in file", metavar="FMT")
argparser.add_argument("-p", "--profile", action="store_true",
                    help="whether to profile the parser")
argparser.add_argument(
    "-o",
    "--output",
    default="pdf",
    choices=["dvi", "pdf", "html-reflow"],
    help="shipout output format. Relative output paths are derived from the jobname in the project directory.",
)
argparser.add_argument(
    "-s",
    "--sort",
    default=None,
    choices=["calls", "cumulative", "filename", "line", "module", "name", "nfl", "pcalls", "stdname", "time"],
    help="sorting key for profile results (used with --profile). Default is time (tottime).",
)
argparser.add_argument(
    "--project-dir",
    default=os.getcwd(),
    help="project directory for source file reads. Defaults to the current working directory.",
)
argparser.add_argument("file")
args = argparser.parse_args()


DOCUMENT_METADATA_SNIPPET = "\\DocumentMetadata{backend=dvipdfmx}"

if args.sort is not None and not args.profile:
    print("Warning: --sort/-s has no effect without --profile", file=sys.stderr)

if args.format != "initex":
    # load the selected output backend
    if args.output == "dvi":
        import pytex.dvi
    elif args.output == "pdf":
        import pytex.pdf
    elif args.output == "html-reflow":
        from pytex import html_reflow as html_reflow_backend

parser = Parser(project_dir=args.project_dir)
if html_reflow_backend is not None:
    parser.shipout = html_reflow_backend.HTMLReflowBackend(parser)
parser.resolver.format = args.format

# tracing settings
#parser.tracingcommands = 2
#parser.tracingmacros = 1
#parser.tracingsource = "latex.ltx"
#parser.tracinglinebegin = 1670
#parser.tracinglineend = 1670
#parser.tracingstopatend = 1

def dumper(parser, data):
    with open(parser.resolver.format + '.pfmt', "wb") as fmt:
        fmt.write(data)
parser.dumper = types.MethodType(dumper, parser)

if args.profile:
    parser.console = open(os.devnull, "w")

source = args.file
dir = os.path.dirname(source)
base = os.path.basename(source)
file, ext = os.path.splitext(base)

if args.format == "initex":
    if ext == "" and source != "plain": # no extension
        source += ".ini"
    parser.resolver.format = file
    print(
        f"the format is initex. Will dump the format {parser.resolver.format} to {parser.resolver.format}.pfmt",
        file=parser.console,
    )
else:
    parser.resolver.format = args.format
    fmt = parser.resolver.openIn(args.format, "dump")
    if fmt is None:
        raise ValueError(f"cannot find format {args.format}")
    parser.load(fmt)
    fmt.close()

input = parser.resolver.openIn(source, "source")
if input is None:
    raise ValueError(f"cannot find {source}")

def run_document():
    if args.format != "initex" and parser.equitable["\\DocumentMetadata"] is not None:
        parser.readFrom(input, file)
        parser.parse(DOCUMENT_METADATA_SNIPPET, jobname=file)
    else:
        parser.parse(input, jobname=file)
    input.close()
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
    exit(0)
else:
    run_document()

if args.format == "initex":
    parser.dumper(parser.dump())

parser.close()
