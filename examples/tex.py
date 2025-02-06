from pathlib import Path
import sys
path = str(Path(Path(__file__).parent.absolute()).parent.absolute())
sys.path.insert(0, path)

from pytex.parser import Parser
from pytex import lists
# load the texlive module to 
import pytex.texlive
from pytex.serialization import serialize
from argparse import ArgumentParser
import os
import json


argparser = ArgumentParser()
argparser.add_argument("-f", "--format", required=True,
                    help="load the format FMT", metavar="FMT")
argparser.add_argument("file")
args = argparser.parse_args()

parser = Parser()
parser.resolver.format = args.format
fmt = parser.resolver.openIn(args.format, "dump")
parser.load(fmt)
fmt.close()
input = parser.resolver.openIn(args.file, "source")
parser.parse(input)
input.close()
try:
    log = parser.end()
except ValueError as e:
    print(parser.logContent())
    raise e

result = open(args.file+".json", "w")
result.write(json.dumps(serialize(parser.lists[0])))
result.close()

print(log)

