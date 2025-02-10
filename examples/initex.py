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
out = os.path.join(args.output, args.fmt+'.json')
with open(out, "w") as fmt:
    if args.fmt == "plain":
        source = parser.resolver.openIn("plain", "source/tex")
    else:
        source = parser.resolver.openIn(args.fmt, "source/ini")
    parser.parse(source)
    source.close()
    parser.dump(fmt)
    