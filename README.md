# pytex

Pytex is a TeX engine reimplemented in Python 3.

It implements the minimal set of pdfTeX primitives needed by LaTeX2e.

Supported output formats include:

- DVI (without TTF/OTF font support)
- XDV
- PDF
- SVG
- DOCX
- reflowable HTML (without pages)

The compiler is available as `python -m pytex`. Pytex also provides a flexible
module framework: parser components, pipe commands (currently `extractbb` for
extracting PDF image bounding boxes), and typesetting backends can be extended
or replaced by modules.

Pytex supports UTF-8 input and output natively, including TTF/OTF fonts. System
fonts can be selected by typeface name, for example:

```tex
\font\a={Times New Roman}
{\a Some text}
```

CJK text works the same way with a suitable system font. TTF/OTF output is
currently supported by the PDF, SVG, DOCX, and reflowable HTML backends.

## Status and limitations

Pytex is an actively developed compatibility implementation rather than a
drop-in replacement for a full TeX distribution. It does not currently support
leaders or the e-TeX extension `\mid`; it implements the subset of pdfTeX
primitives needed by LaTeX2e. The DOCX and HTML backends are reflowable, so
their rendering is constrained by the target application's layout and font
support.

## Requirements

- Python 3.9 or newer
- A TeX Live installation containing the source files, fonts, metrics, and
  hyphenation data used to build and run formats

Pytex currently requires TeX Live even though Plain TeX, ePlain, and LaTeX
format files are bundled with the package. The bundled files avoid an initial
format dump, but TeX Live still supplies package inputs, Type 1/OpenType font
programs and metrics, and hyphenation data while a document is compiled.

Pytex searches the following default TeX Live roots and selects the greatest
numeric release directory beneath the root:

- macOS: `/usr/local/texlive`
- Linux: `/usr/share/texlive`
- Windows: `C:\texlive`

For example, `/usr/local/texlive/2025/texmf-dist` is recognized on macOS. The
command-line compiler reports an error at startup if it cannot find a TeX Live
installation in the expected layout.

## Install from a fresh checkout

Clone the repository, create an isolated environment, and install the checkout
in editable mode:

```console
git clone https://github.com/roverrobot/pytex.git
cd pytex
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

On Windows, activate the environment with:

```console
.venv\Scripts\activate
```

Editable installation is useful for development because changes in the
checkout take effect without reinstalling the package. For a regular install
from the checkout, use `python -m pip install .` instead.

Verify the installation:

```console
python -m pytex --help
```

To run the test suite, install the test extra:

```console
python -m pip install -e ".[test]"
python -m pytest
```

## Install directly from GitHub

A checkout is not required. Create and activate a virtual environment as above,
then install the current `main` branch directly:

```console
python -m pip install "git+https://github.com/roverrobot/pytex.git@main"
python -m pytex --help
```

Replace `main` with a tag or commit hash to install a specific revision.

## Bundled and custom format files

Pytex includes ready-to-use format files for Plain TeX, ePlain, and LaTeX, for
both the `xetex` and `pdftex` compatibility layers. No initial format dump is
needed for these standard formats. For example, compile a LaTeX document with:

```console
python -m pytex --engine xetex --format latex --output pdf document.tex
```

The engine suffix is added automatically: `--format latex --engine xetex`
loads `latex-xetex.pfmt`, while `--engine pdftex` loads `latex-pdftex.pfmt`.
The bundled formats are compressed, generated from TeX Live 2023, and their
source provenance and redistribution notes are recorded in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

To use a format not bundled with Pytex, such as ConTeXt, first dump it from the
appropriate TeX Live initializer. Format dumping is the default `--format
initex` mode; the explicit form is:

```console
python -m pytex --format initex --engine xetex path/to/context.ini
```

This writes `context-xetex.pfmt` to the current working directory. Use the
matching format name and engine to compile a document:

```console
python -m pytex --format context --engine xetex document.tex
```

The initializer and supported engine depend on the format's TeX Live
installation. The same approach applies to any other non-bundled format.

You may also regenerate the bundled formats, for example to test a locally
modified TeX Live tree:

```console
python -m pytex --engine xetex plain
python -m pytex --engine xetex eplain.ini
python -m pytex --engine xetex latex.ltx
```

Each command writes an engine-specific `.pfmt` file to the current working
directory. A local format file takes precedence over the bundled copy, which
makes these commands a convenient override mechanism.

## Command-line flags

The general command form is:

```console
python -m pytex [options] file
```

### `file`

The input file to initialize or compile. In `--format initex` mode it is the
format initializer, such as `plain`, `eplain.ini`, or `latex.ltx`. When loading
a dumped format, it is the document to compile.

### `-f FMT`, `--format FMT`

Selects the format to load. The default, `initex`, initializes the engine from
the input and dumps a new format. Any other value loads that named,
engine-specific format; Plain TeX, ePlain, and LaTeX are bundled, while other
formats must first be dumped locally.

### `-e ENGINE`, `--engine ENGINE`

Selects the engine compatibility layer. Choices are `xetex` (the default) and
`pdftex`. Use the same engine when dumping and loading a format.

### `-o OUTPUT`, `--output OUTPUT`

Selects the shipout backend when compiling a document. The default is `pdf`.
Choices are `dvi`, `xdv`, `pdf`, `html-reflow`, `docx`, and `svg`. Relative
output paths are derived from the input job name in the project directory. This
option does not affect the format produced in `initex` mode.

For example:

```console
python -m pytex -e xetex -f latex -o docx document.tex
```

### `--project-dir DIRECTORY`

Sets the project directory used for source reads and document outputs. It
defaults to the current working directory. The generated `.pfmt` file in
`initex` mode is always written to the current working directory.

### `--texlive DIRECTORY`

Uses a TeX Live installation rooted at `DIRECTORY` instead of the platform
default. The directory must contain release directories such as
`DIRECTORY/2026/texmf-dist`. This is useful for a portable, testing, or
nonstandard TeX Live installation:

```console
python -m pytex --texlive /opt/texlive -f latex document.tex
```

### `-p`, `--profile`

Runs the parser under Python's profiler and prints profiling statistics after
the run.

### `-s KEY`, `--sort KEY`

Sorts profiling output. It has no effect unless `--profile` is also supplied.
The default profiling sort is `time`. Available keys are `calls`, `cumulative`,
`filename`, `line`, `module`, `name`, `nfl`, `pcalls`, `stdname`, and `time`.

For example:

```console
python -m pytex -p -s cumulative -f latex document.tex
```

### `-h`, `--help`

Prints the command-line help and exits.
