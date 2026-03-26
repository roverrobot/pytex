from pathlib import Path
import sys
path = str(Path(Path(__file__).parent.absolute()).parent.absolute())
sys.path.insert(0, path)
import cProfile
from pytex.parser import Parser
# load the texlive module to resolve files in the texlive tree
from pytex import texlive
from pytex import etex
# latex would require pdftex
from pytex import pdftex
# dvi output
from pytex import dvi

from argparse import ArgumentParser
import os
import types


argparser = ArgumentParser()
argparser.add_argument("-f", "--format", default="initex",
                    help="load the format FMT. If FMT is initex, it dumps a format file. The format is provided in file", metavar="FMT")
argparser.add_argument("-p", "--profile", action="store_true",
                    help="whether to profile the parser")
argparser.add_argument(
    "-o",
    "--output",
    default=None,
    help="output file name for shipout backends (for example the DVI file name)",
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

if args.sort is not None and not args.profile:
    print("Warning: --sort/-s has no effect without --profile", file=sys.stderr)

parser = Parser(project_dir=args.project_dir)

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
parser.resolver.format = file

if args.format == "initex":
    if ext == "" and parser.resolver.format != "plain": # no extension
        source += ".ini"
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

if args.profile:
    # disable tex engine console output
    profile_sort = args.sort if args.sort is not None else "time"
    cProfile.run("parser.parse(input)", sort=profile_sort)
    # no need tto dump. stop
    parser.console.close()
    exit(0)
else:
    if args.format != "initex":
        parser.shipout = dvi.DVIShipout(parser, args.output)
    parser.parse(input, jobname=file)
input.close()

if args.format == "initex":
    parser.dumper(parser.dump())
else:
    parser.end()

log = parser.close()

print("log file content")
print(log)
