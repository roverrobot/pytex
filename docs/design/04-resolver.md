# Resolver Layer

This note describes the file-resolution framework used by the parser.

It sits next to the input layer. The input layer explains how tokens are read
and scheduled once a stream has already been opened. The resolver layer explains
how the engine finds and opens those streams in the first place, and how the
same mechanism is reused for fonts, format files, and backend output files.

The current implementation is centered on `resolver.py`, with the main TeX Live
backend in `texlive.py`.

## Scope

This note covers:

- the `FileResolver` abstraction in `resolver.py`
- the default resolver module installed on `Parser`
- the `TexliveResolver` backend in `texlive.py`
- file-type classification and path policy
- parser-facing helpers such as `readFileName`
- the main current uses of the resolver in `\input`, `\openin`, `\openout`,
  format loading, font loading, and shipout backends
- allowlisted pipe-backed input at a high level

This note does not try to explain:

- token flow after a file has been opened
- the full pipe-command framework
- backend-specific shipout formats in detail
- font metrics or font backend internals in detail

Those belong to later notes.

## Main Role

The resolver is the engine's policy object for turning a TeX-level file name
into an actual readable or writable stream.

That includes more than source files. In the current code, the same resolver
interface is used for:

- source input such as `\input`
- explicit file I/O such as `\openin`, `\openout`, `\read`, and `\write`
- format loading and dumping from the entry script
- TFM and OpenType font lookup
- backend output files such as DVI, PDF, and HTML-reflow output
- allowlisted pipe-backed input streams

So the resolver layer is not just a utility for `\input`. It is the common file
and path policy for the engine.

## Core Abstraction

The base class is `FileResolver` in `resolver.py`.

Its main public operations are:

- `openIn(name, type=None)`
- `openOut(name, type)`
- `resolve(info)`
- `clone(project_dir=None)`

The intended split is:

- `openIn` and `openOut` implement the generic opening policy
- `getInfo` classifies names by category and subcategory
- `resolve` is the backend hook that subclasses override to perform external
  search
- `clone` gives each `Parser` its own resolver instance, even when the module
  registry stores a shared prototype

In other words, `FileResolver` is a policy layer with overridable lookup, not
just a thin path helper.

## File Categories

The resolver classifies files by category and subcategory.

The current built-in categories are:

- `fonts`
  - `tfm`
  - `afm`
  - `type1`
  - `opentype`
  - `truetype`
- `dump`
  - `pfmt`
- `shipout`
  - `dvi`
  - `pdf`
- `source`
  - `tex`
  - `ini`

This classification does three things.

First, it determines the default extensions that should be tried.

Second, it determines whether the file should be opened in text or binary mode.

Third, it determines which search policy applies. Source files are treated
specially, because they are allowed to come from the project directory, while
other categories typically use the current working directory first and then the
resolver backend.

## Parser Integration

The resolver is installed as part of the module framework.

The base resolver module in `resolver.py` provides:

- `parser.resolver`, initially a `FileResolver()` instance
- `parser.readFileName`, a parser-facing helper for TeX-style file-name
  scanning

The `texlive` module in `texlive.py` overrides `parser.resolver` with a
`TexliveResolver(format="plain")` instance.

As with other modules, these are installed by import side effect. `parser.py`
imports `resolver` directly, and a caller may import `pytex.texlive` before
constructing a `Parser` in order to replace the default resolver with the TeX
Live resolver.

`Parser.__init__` then clones the configured resolver, so parsers do not share
mutable resolver state such as:

- the project directory
- in-memory files
- parser-local configuration

This is an important detail. The module registry holds resolver prototypes, but
each parser gets its own working resolver instance.

## Project Directory Policy

The current code gives source files and output files an explicit project-root
policy.

### Source Reads

For source files, `openIn(..., "source")` first tries:

- in-memory files
- the project directory
- resolver backend search, if the name is not an explicit path

Relative source paths are resolved under `parser.resolver.project_dir`.
Absolute source paths are allowed only if they stay inside that project
boundary.

Paths outside the project directory are rejected.

This means the resolver is not just a search mechanism. It also enforces a
source-access policy.

### Output Writes

For output files, `openOut` writes under the project directory.

Relative output paths are resolved inside that directory. Absolute output paths
are rejected. Escapes outside the project directory are also rejected.

This is the policy used by shipout backends and by explicit file-writing
commands.

## In-Memory Files

`resolver.py` also provides in-memory file objects:

- `InMemoryTextFile`
- `InMemoryBinaryFile`

These support two current use cases.

The first is testing. A parser can be given synthetic source or output files
without touching the filesystem.

The second is optional in-memory output mode. If `output_in_memory=True`,
`openOut` creates in-memory files instead of real files on disk.

The resolver keeps these in `resolver.in_memory_files` and checks them before
falling back to filesystem or backend search.

## TeX-Style File Names

The parser-facing helper `readFileName` lives in `resolver.py` and is installed
as a parser method by the resolver module.

This is important because TeX file names are not read as ordinary Python
strings. The helper reads a file name from token flow using current parser
behavior, including expansion where appropriate.

The current helper supports:

- quoted file names such as `"two words.tex"`
- brace-delimited names, with token expansion during the read
- ordinary unquoted names terminated by space or control-sequence boundaries

This helper is used by more than `\input`. It is also used by `\openin`,
`\openout`, and font loading commands.

So the resolver layer begins with TeX-level name reading, not only with
filesystem lookup.

## Resolution Order For Reads

`FileResolver.openIn` follows a clear order.

### 1. Pipe-backed input

If the name begins with `|`, the resolver first tries `openPipeIn`.

This does not execute an arbitrary shell command. It dispatches through the
allowlisted pipe-command registry in `pytex.pipes` and returns a read-only text
stream if a registered handler accepts the command.

We only need that high-level fact here. The pipe-command framework itself should
be explained separately.

### 2. In-memory files

If the requested name matches an in-memory file, the resolver opens that object
first.

### 3. Direct filesystem policy

If the file is a source file, the resolver tries the project directory.

If the file is not a source file, it tries the current working directory.

If the user supplied an explicit directory component and the direct open fails,
the resolver stops there and does not fall through to backend search.

### 4. Backend resolution

Only after those steps does the resolver call `resolve(info)`.

For the base `FileResolver`, `resolve` does nothing. For subclasses such as
`TexliveResolver`, this is where external search happens.

## Resolution Order For Writes

`FileResolver.openOut` is simpler.

It classifies the requested type, chooses text or binary mode, normalizes the
output name, and then writes either:

- to an in-memory file, if `output_in_memory` is enabled, or
- to a real file under the project directory

Unlike reads, writes do not go through a backend search path.

## TeX Live Backend

The main current backend subclass is `TexliveResolver` in `texlive.py`.

Its role is to search a TeX Live installation when the generic resolver policy
has not already found a file.

### Search Roots

`TexliveResolver` looks for the most recent TeX Live year under the platform's
base TeX Live directory and then uses:

- `<year>/texmf-dist`
- `texmf-local`, if present

The `format` attribute controls source search. For source files it searches in
format-specific trees such as:

- `tex/<format>`
- `tex/generic`
- `tex/plain`, unless the format is already `plain`

For other categories, it searches category/subcategory paths such as:

- `fonts/tfm`
- `fonts/opentype`
- `shipout/pdf`

### Cached Directory Index

The current TeX Live resolver does not repeatedly walk the same trees.

Instead, it caches the first matching full path for each file name under a
search root. That cache is process-wide and shared by parser-local resolver
clones.

So the expensive directory walk happens once per searched root, not once per
parser.

## Current Uses In The Engine

The resolver appears in several important places.

### `\input`

The `\input` command reads a TeX file name with `parser.readFileName()`, opens
it with `parser.resolver.openIn(name, "source")`, and then pushes a new
`Tokenizer` onto `parser.input`.

So `\input` is the clearest bridge from the resolver layer into the token-flow
layer.

### `\openin`, `\openout`, `\read`, `\write`

The file commands in `file.py` use the resolver as follows:

- `\openin` stores a readable stream returned by `resolver.openIn(..., "source")`
- `\openout` stores a writable stream returned by `resolver.openOut(..., "source")`
- `\read` reads from an already opened stream
- `\write` writes expanded text to an already opened stream

The important point is that the resolver owns opening policy, while the file
commands own TeX-level I/O semantics after the stream exists.

### Format Loading And Dumping

The `python -m pytex` entry point in `pytex/__main__.py` also uses the resolver directly.

It sets the parser's format on the resolver and then:

- opens the selected format with `parser.resolver.openIn(args.format, "dump")`
- opens the document source with `parser.resolver.openIn(source, "source")`
- relies on `parser.resolver.format` to control format-relative TeX Live source
  lookup

So the resolver layer is already part of the executable front end, not only the
interpreter core.

### Font Lookup

Font loading also uses the resolver.

The current code resolves:

- TFM files through `parser.resolver.openIn(name, "fonts/tfm")`
- named OpenType and TrueType files through `parser.resolver.openIn(name, type)`

If an OpenType font name has no explicit extension, the OpenType backend first
tries system-font matching. If the name has a known font-file extension, it
uses the resolver.

So the resolver participates in both traditional TeX font lookup and modern
font-file lookup.

### Backend Output

Backends use the resolver for output files as well.

For example:

- the DVI backend opens its output with `resolver.openOut(path, "shipout/dvi")`
- the PDF backend opens its output with `resolver.openOut(path, "shipout/pdf")`
- the HTML reflow backend opens output through `resolver.openOut(path, None)`

So the same layer controls both reading and writing across the engine.

### PDFTeX-style File Probes

Some pdfTeX-compatible expandable commands also use the resolver to probe or
open source files. These commands add a few compatibility rules, such as
special treatment of `/dev/null`, but ordinary relative file lookup still goes
through `parser.resolver.openIn(name, "source")`.

## Why This Layer Matters

The resolver is not just plumbing.

It separates three concerns that would otherwise be mixed into command logic:

- TeX-level file-name scanning
- path and access policy
- backend-specific search, such as TeX Live lookup

That separation is useful for several reasons.

- `Parser` does not need to hard-code filesystem rules.
- Commands such as `\input` and `\openin` stay focused on TeX semantics.
- Different environments can swap in different resolver backends as modules.
- Tests can replace real files with in-memory files.
- Source and output paths can be restricted to the project directory.

## Relationship To Neighboring Notes

In the design-note sequence, this note fits after token flow.

- the token-flow note explains how opened token sources are scheduled and read
- this resolver note explains how those sources are found and opened
- later notes can then return to execution semantics, parser state, and parser
  ownership

The one place where this note intentionally stops early is pipe-backed input.
The resolver note only needs to say that names beginning with `|` are resolved
through an allowlisted registry. The detailed contract for those pipe commands
belongs in a separate note.

## Summary

The current resolver layer consists of a parser-installed `FileResolver`
interface, a `TexliveResolver` backend, and a parser-facing `readFileName`
helper.

Its responsibilities are:

- classify files by category and subcategory
- enforce project-directory policy for source reads and output writes
- support in-memory files for testing and optional output capture
- search TeX Live when direct opens do not find a file
- provide the common opening mechanism used by source input, explicit file I/O,
  format loading, font lookup, and backend output
- dispatch allowlisted pipe-backed reads without exposing arbitrary shell
  execution

That makes it a distinct layer in the engine: not token flow itself, and not
command semantics themselves, but the shared policy for turning TeX-level names
into concrete streams.
