# Design Notes

Read in this order:

* [01-layer-separation.md](01-layer-separation.md): how the parser functions are divided into layers
* [02-module.md](02-module.md): how the parser is modularized
* The tokenization layer:
    * [03-token-flow.md](03-token-flow.md): the "mouse" of the tex engine, how tokens are fed into the execution layer
    * [04-resolver.md](04-resolver.md): how file names are resolved
        * [05-pipe-backends.md](05-pipe-backends.md) how the pipes (shell escapes) are implemented 
* The execution layer:
    * [06-parser-state.md](06-parser-state.md)
    * [07-parser-kernel.md](07-parser-kernel.md)
    * [08-assignment-ir.md](08-assignment-ir.md)
    * [09-list-construction.md](09-list-construction.md)
    * [10-font-backends.md](03-font-backends.md)
* Typesetting and shipping out:
    * [11-typeset-backends.md](11-typeset-backends.md)
    * [12-shipout-ir.md](11-shipout-ir.md)
    * [13-special-ir.md](13-special-ir.md)
* Shipout backends:
    * [14-pdf-backend.md](14-pdf-backend.md)
    * [15-html-reflow-backend.md](15-html-reflow-backend.md)
    * [16-html-faithful-backend-proposal.md](16-html-faithful-backend-proposal.md)
    * [17-docx-faithful-backend-proposal.md](17-docx-faithful-backend-proposal.md)
    * [18-reflow-document-ir.md](18-reflow-document-ir.md)
* Proposed text-layout refactor:
    * [19-text-runs-and-glyph-clusters.md](19-text-runs-and-glyph-clusters.md)
