# pytex

Pytex is a TeX engine reimplemented in Python 3.

It does not currently support leaders or the e-TeX extension `\mid`. It
implements the minimal set of pdfTeX primitives needed by LaTeX2e.

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

## Requirements

- Python 3.9 or newer
- A TeX Live installation containing the source files, fonts, metrics, and
  hyphenation data used to build and run formats

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

Verify the installation and, optionally, run the test suite:

```console
python -m pytex --help
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

## Dump format files

Pytex loads its runtime state from `.pfmt` format files. These generated files
are engine-specific, so a format dumped with the XeTeX compatibility layer must
also be loaded with `--engine xetex`; the same rule applies to pdfTeX.

Run the dump commands in the directory where you want to keep the format files.
The default engine is `xetex`, so the following commands create the standard
XeTeX-compatible formats:

```console
python -m pytex plain
python -m pytex eplain.ini
python -m pytex latex.ltx
```

They produce:

```text
plain-xetex.pfmt
eplain-xetex.pfmt
latex-xetex.pfmt
```

`plain` is a special extensionless input name. Other extensionless initializer
names are treated as `.ini` files, so `eplain` and `eplain.ini` are equivalent.
LaTeX is initialized from `latex.ltx`. Pytex resolves all three inputs through
the installed TeX Live tree. Building eplain or LaTeX can take considerably
longer than building plain.

To build pdfTeX-compatible formats instead, select that engine explicitly:

```console
python -m pytex --engine pdftex plain
python -m pytex --engine pdftex eplain.ini
python -m pytex --engine pdftex latex.ltx
```

These commands produce `plain-pdftex.pfmt`, `eplain-pdftex.pfmt`, and
`latex-pdftex.pfmt`.

Format dumping is selected by the default `--format initex` mode. The explicit
equivalent is:

```console
python -m pytex --format initex --engine xetex latex.ltx
```

The `.pfmt` file itself is written to the current working directory. Keep it in
the project directory from which you compile, or in the directory supplied with
`--project-dir`, so that Pytex can find it later.

For example, after dumping `latex-xetex.pfmt`, compile a document with:

```console
python -m pytex --engine xetex --format latex --output pdf document.tex
```

The engine suffix is added automatically when a format is loaded. For example,
`--format latex --engine xetex` looks for `latex-xetex.pfmt`.

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
the input and dumps a new format. Any other value loads that named format; for
example, `--format latex` loads the engine-specific `latex-*.pfmt` file.

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
