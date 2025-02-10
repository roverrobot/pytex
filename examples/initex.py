from pathlib import Path
import sys
path = str(Path(Path(__file__).parent.absolute()).parent.absolute())
sys.path.insert(0, path)

from pytex.parser import Parser
# load the texlive module to find files
from pytex import texlive
from argparse import ArgumentParser
import os
from pytex import etex

output = "."

argparser = ArgumentParser()
argparser.add_argument("-o", "--output", default=".",
                    help="write the format files to DIR", metavar="DIR")
argparser.add_argument("fmt")
args = argparser.parse_args()

parser = Parser()
parser.resolver.format = args.fmt

def dumper(data):
    with open(os.path.join(args.output, args.fmt+'.json'), "w") as fmt:
        fmt.write(data)
parser.dumper = dumper

if args.fmt == "plain":
    source = parser.resolver.openIn("plain", "source/tex")
else:
    source = parser.resolver.openIn(args.fmt, "source/ini")
parser.parse(source)

# the texlive's plain format does not dump the state
# so we need to do it manually
if args.fmt == "plain":
    dump = parser.dump()
    if dump:
        parser.dumper(dump)
