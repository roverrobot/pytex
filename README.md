= pytex

This is a tex compiler re-implemented in Python 3.

Currently, it does not support typesetting yet, but will be implemented in a later version.
These features include
* typesetting math formula
* line breaking
* pagebreaking
* output routings
* leaders

It currently only support plain tex. Eventually etex and a minimal version of the pdftex will
be implemented, so that latex parsing is viable.

In addition, tracing commands are not implemented. However, this parser is more flexible, and can
incrementally parse a documnet. The internal state of the parser are always available for
examination. 
