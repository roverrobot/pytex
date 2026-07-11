= pytex

This is a tex engine re-implemented in Python 3.

Currently, it does not support leaders and the etex extension \mid. It implements a minimal set of pdftex premitives that are needed for latex2e. 

It currently supports the following output formats:
* dvi (no ttf/otf font support)
* pdf
* html-reflow (no pages)

The compiler is available as `python -m pytex`. It supports format dumping and the available output backends; for example, `python -m pytex -f latex -o docx document.tex`.

This engine provides a very flexible module framework, where parts of the parser can be extended or even replaced using modules. In addition, pipe commands (currently extractbb for extracting boundin boxes for pdf images) and typeset backends are all provided using modules.

It supports utf-8 input and output natively, with native supports to ttf/otf fonts. A convenient extension is use system-wide fonts by type face names such as \font\a={Times New Roman}. CJK support is thus automatic: we first select a font, then use the font and directly type the characters (currently only pdf and html-reflow backends support it because it uses ttf/otf fonts). For example: \font\a={Baoli SC} {\a 中文}
