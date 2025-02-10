from pathlib import Path
import sys
path = str(Path(Path(__file__).parent.absolute()).parent.absolute())
sys.path.insert(0, path)

from pytex.parser import Parser
from pytex import lists
# load the texlive module to resolve files in the texlive tree
from pytex import texlive
# support the etex extensions
from pytex import etex
from pytex.serialization import serialize

from argparse import ArgumentParser
import os
import json


argparser = ArgumentParser()
argparser.add_argument("-f", "--format", default="initex",
                    help="load the format FMT. If FMT is initex, it dumps a format file. The format is provided in file", metavar="FMT")
argparser.add_argument("file")
args = argparser.parse_args()


parser = Parser()

def dumper(data):
    with open(parser.resolver.format+'.json', "w") as fmt:
        fmt.write(data)
parser.dumper = dumper

if args.format == "initex":
    if os.path.isabs(args.file):
        raise ValueError("The file must be a relative path")
    path = Path(args.file)
    parts = Path(args.file).parts
    file = parts[-1] if len(parts) > 1 else parts[0]
    file_parts = os.path.splitext(file)
    parser.resolver.format = file_parts[0]
    source = args.file
    if len(file_parts) > 1 and parser.resolver.format != "plain": # no extension
        source += ".ini"
    print(f"the format is initex. Will dump the format {parser.resolver.format} to {parser.resolver.format}.json")
else:
    parser.resolver.format = args.format
    fmt = parser.resolver.openIn(args.format, "dump")
    parser.load(fmt)
    fmt.close()
    source = args.file

input = parser.resolver.openIn(source, "source")
parser.parse(input)
input.close()

try:
    log = parser.end()
except ValueError as e:
    print(parser.logContent())
    raise e

if args.format == "initex":
    dump = parser.dump()
    if dump != "{}":
        dumper(dump)
else:
    result = open(args.file+".json", "w")
    result.write(json.dumps(serialize(parser.lists[0])))
    result.close()

print("log file content")
print(log)

