"""
This module contains the system interface for the pdftex engine.
"""

from pytex import token
from pytex.module import Module
from pytex.integer import FixedInteger
from pytex.accessor import ReadOnlyTarget, VALUE_TYPE
import time


class PDFElapsedtime(token.Command):
    """
    The \\pdfelapsedtime command.
    """
    def execute(self, parser):
        """
        Execute the command. The pdfelapsedtime command returns the elapsed time in seconds since the start of the TeX run.
        @param parser: the parser
        """
        pass

    def getTarget(self, parser):
        return ReadOnlyTarget(int(time.time() - parser.timer), VALUE_TYPE.INT)

    def intValue(self, parser):
        """
        Get the integer value of the command.
        @param parser: the parser
        @return: the integer value
        """
        return int(time.time() - parser.timer)


class PDFResettimer(token.Command):
    """
    The \\pdfresettimer command.
    """
    def execute(self, parser):
        """
        Execute the command. The pdfresettimer command resets the timer.
        @param parser: the parser
        """
        parser.timer = time.time()


def init(parser):
    parser.timer = time.time()


mod = Module("pdftex.sys",
    init=init,
    commands={
        "pdfelapsedtime": PDFElapsedtime(),
        "pdfresettimer": PDFResettimer(),
        # shell escape is always disabled
        "pdfshellescape": FixedInteger(0),
    },
)
