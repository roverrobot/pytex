"""Default virtual shipout backend."""

from pytex import node as nd


class Shipout:
    """
    Default shipout collector.
    """

    def __init__(self, parser, output=None):
        self.parser = parser
        self.output = output
        self.pages = []

    def shipout(self, box):
        self._flushWhatsits(box)
        self.pages.append(box)

    def _flushWhatsits(self, box):
        items = getattr(box, "list", None)
        if items is None:
            return
        for node in items:
            if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                self._flushWhatsits(node)
                continue
            if node.node_type == nd.NODE_TYPE.WHATSIT:
                node.output(self.parser, self)

    def special(self, text):
        pass

    def __enter__(self):
        self.open()
        return self
    
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def open(self):
        pass

    def close(self):
        pass

