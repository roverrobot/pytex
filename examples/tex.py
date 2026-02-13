from pathlib import Path
import sys
path = str(Path(Path(__file__).parent.absolute()).parent.absolute())
sys.path.insert(0, path)
import cProfile
from pytex.parser import Parser
from pytex import lists
# load the texlive module to resolve files in the texlive tree
from pytex import texlive
from pytex.serialization import serialize
# lagtex would require pdftex
from pytex import pdftex

from argparse import ArgumentParser
import os
import json
import types


argparser = ArgumentParser()
argparser.add_argument("-f", "--format", default="initex",
                    help="load the format FMT. If FMT is initex, it dumps a format file. The format is provided in file", metavar="FMT")
argparser.add_argument("-p", "--profile", action="store_true",
                    help="whether to profile the parser")
argparser.add_argument(
    "-s",
    "--sort",
    default=None,
    choices=["calls", "cumulative", "filename", "line", "module", "name", "nfl", "pcalls", "stdname", "time"],
    help="sorting key for profile results (used with --profile). Default is time (tottime).",
)
argparser.add_argument("file")
args = argparser.parse_args()

if args.sort is not None and not args.profile:
    print("Warning: --sort/-s has no effect without --profile", file=sys.stderr)


parser = Parser()

# tracing settings
#parser.tracingcommands = 2
#parser.tracingmacros = 1
#parser.tracingsource = "latex.ltx"
#parser.tracinglinebegin = 1670
#parser.tracinglineend = 1670
#parser.tracingstopatend = 1


def dumper(parser, data):
    with open(parser.resolver.format+'.json', "w") as fmt:
        fmt.write(data)
parser.dumper = types.MethodType(dumper, parser)

if args.profile:
    parser.console = open(os.devnull, "w")

if args.format == "initex":
    if os.path.isabs(args.file):
        raise ValueError("The file must be a relative path")
    path = Path(args.file)
    parts = path.parts
    file = parts[-1] if len(parts) > 1 else parts[0]
    file_parts = os.path.splitext(file)
    parser.resolver.format = file_parts[0]
    source = args.file
    if len(file_parts) > 1 and file_parts[1] == "" and parser.resolver.format != "plain": # no extension
        source += ".ini"
    print(f"the format is initex. Will dump the format {parser.resolver.format} to {parser.resolver.format}.json", file = parser.console)
else:
    parser.resolver.format = args.format
    fmt = parser.resolver.openIn(args.format, "dump")
    parser.load(fmt)
    fmt.close()
    source = args.file

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
    parser.parse(input)
input.close()
log = parser.end()

if args.format == "initex":
    parser.dumper(parser.dump())
else:
    result = open(args.file+".json", "w")
    result.write(json.dumps(serialize(parser.lists[0])))
    result.close()

print("log file content")
print(log)
