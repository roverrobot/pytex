# Special IR

This note defines a backend-neutral intermediate representation for
driver-oriented `\special` commands, with `dvipdfm`/`xdvipdfmx` specials as the
first target.

The main design goal is to parse specials once and then translate the result
into multiple shipout backends, including:

- page-aware HTML
- direct PDF output
- future faithful HTML/CSS rendering

The DVI backend remains free to emit raw specials unchanged. It does not need to
round-trip through this command IR.

## Goals

- Treat `dvipdfm` specials as a first-class input language.
- Separate parsing from backend rendering.
- Define an IR that captures page/document semantics rather than raw driver
  strings.
- Keep room for both page-local operations and document-level objects such as
  destinations and outlines.
- Support incremental implementation: colors and transforms first, more
  elaborate PDF object commands later.

## Non-Goals

- Full raw PostScript compatibility.
- Full `dvips` special support.
- A literal reproduction of PDF syntax as the public backend API.
- Mandatory support for every historical `dvipdfm` command in the first pass.

## Input Model

At the TeX level, `\special{...}` already becomes a whatsit-like node carrying a
raw string.

For backend-neutral processing, specials should move through three phases:

1. raw special text
2. typed special command object
3. backend-specific lowering

This separation matters because the `dvipdfm` syntax uses PDF-like literals,
dimensions, transformations, and driver variables, but HTML and future PDF
backends should not be forced to consume raw `pdf:` command strings directly.

## Parsing Boundary

Only specials beginning with `pdf:` belong to the first parser.

Other legacy special families such as:

- `color ...`
- `psfile=...`
- HyperTeX
- TPIC
- raw `ps:`

should be handled by separate compatibility parsers or adapters later.

This note only covers the `pdf:` command family.

## Pipeline

The pipeline should look like this:

```text
raw Special text
  -> dvipdfm special parser
  -> typed command object
  -> HTML renderer / PDF renderer / other backend
```

More concretely:

- the parser recognizes `pdf:` and tokenizes the remainder
- a command dispatcher selects a command subclass
- that command parses and validates its own arguments
- nested PDF-style payloads are parsed by a separate `PdfValue` parser
- the resulting command object is already the IR consumed by backends

## Syntax Front-End

The `dvipdfm` parser needs two front-end pieces:

### 1. Command Name Parsing

The first token after `pdf:` selects the command.

Aliases such as:

- `ann` / `annot` / `annotate`
- `bc` / `bcolor` / `begincolor`
- `bt` / `btrans` / `begintransform`

should normalize to one canonical command name in the AST.

After the command name is known, a factory or dispatcher should instantiate a
specific command subclass. Each command class then parses the rest of the
special according to its own syntax.

So the high-level shape is:

- parse command name
- dispatch to command subclass
- let that class parse its own named arguments and trailing payload

This closely matches the existing TeX command architecture and keeps validation
local to each command type.

### 2. PDF-Like Value Parsing

Many commands use a small PDF-like value language as their payload or as part of
their named arguments. This part should have its own tiny recursive parser.

Suggested value nodes:

- `NameValue`
- `StringValue`
- `NumberValue`
- `ArrayValue`
- `DictValue`
- `BooleanValue`
- `NullValue`
- `VariableRef`

`VariableRef` covers `@name`-style references such as:

- user-defined names like `@mydict`
- driver names like `@thispage`, `@xpos`, `@ypos`

The special parser should not resolve these names immediately. Resolution belongs
to backend lowering.

This value grammar is intentionally small. For the first pass, the important
cases are:

- numbers
- strings like `(text)`
- arrays like `[ value ... ]`
- dictionaries like `<< /Name value ... >>`
- names like `/Type`
- references like `@thispage`

Possible later extensions include booleans, null, and hex strings.

### Named Argument Parsing

Many `dvipdfm` commands are best understood as:

- a command name
- zero or more named arguments
- an optional trailing payload value

For example:

```text
pdf: epdf yscale 0.50 width 4.0in rotate 45 (circuit.pdf)
```

should parse conceptually as:

- command: `epdf`
- named args:
  - `yscale = 0.50`
  - `width = 4.0in`
  - `rotate = 45`
- payload:
  - `(circuit.pdf)`

The command parser should therefore support small typed named arguments such as:

- dimensions: `width 4in`, `height 12pt`, `depth 3pt`
- transforms: `scale 0.5`, `xscale 2`, `yscale 0.5`, `rotate 45`
- image boxes: `bbox llx lly urx ury`

These do not need a generic argument AST. Each command class can parse and
store them in typed fields.

## Command Objects As IR

The typed command objects should themselves be the IR.

There is no need for a second generic operation layer between parsing and
backend lowering if the command classes are already normalized and validated.

So the model is:

- each command is represented by a specific Python class
- each class owns its parsing logic
- each instance is a backend-facing IR node
- nested PDF-like payloads remain represented by `PdfValue` objects

This keeps the architecture small and matches the way TeX commands are already
structured in the engine.

For example, instead of a generic command record:

```python
SpecialCommand(
    name="epdf",
    args={"yscale": NumberValue(0.5), "width": DimensionValue(4.0, "in")},
    payload=StringValue("circuit.pdf"),
)
```

the preferred shape after parsing is a typed command object such as:

```python
EpdfCommand(
    name_ref=None,
    width=DimensionValue(4.0, "in"),
    height=None,
    depth=None,
    scale=None,
    xscale=None,
    yscale=NumberValue(0.5),
    rotate=NumberValue(45),
    bbox=None,
    source=StringValue("circuit.pdf"),
)
```

This object is already good IR for HTML and future PDF backends.

## Command Family Inventory

The command classes should still be grouped conceptually so backends know what
they are consuming.

### Graphics State Commands

- `SetColorCommand`
- `BeginColorCommand`
- `EndColorCommand`
- `BackgroundColorCommand`
- `BeginTransformCommand`
- `EndTransformCommand`

### Page Content Commands

- `BeginPageContentCommand` for `bop`
- `CurrentPageContentCommand` for `content`
- `EndPageContentCommand` for `eop`

These should keep their marking stream as raw text initially.

### Resource Commands

- `BeginXObjectCommand`
- `EndXObjectCommand`
- `UseXObjectCommand`
- `ImageCommand`
- `EpdfCommand`

### Annotation And Navigation Commands

- `AnnotateCommand`
- `BeginAnnotationCommand`
- `EndAnnotationCommand`
- `LinkCommand`
- `NoLinkCommand`
- `DestinationCommand`
- `OutlineCommand`
- `ThreadCommand`

### Document Commands

- `PageSizeCommand`
- `DocInfoCommand`
- `DocViewCommand`

### Object Graph Commands

- `ObjectCommand`
- `PutCommand`
- `CloseCommand`

These remain a low-level escape hatch and may not have meaningful lowering in
all backends.

## Command Family Priority

Implementation should proceed in layers.

### Phase 1

- `setcolor`
- `begincolor`
- `endcolor`
- `bgcolor`
- `begintransform`
- `endtransform`
- `bop`
- `content`
- `eop`

These are the most useful commands for both HTML and future PDF.

### Phase 2

- `beginxobj`
- `endxobj`
- `usexobj`
- `image`
- `epdf`

These give us reusable graphics/image resources and are important for faithful
output.

### Phase 3

- `annotate`
- `beginann`
- `endann`
- `link`
- `nolink`
- `dest`
- `out`
- `thread`

These add navigation and annotations.

### Phase 4

- `pagesize`
- `docinfo`
- `docview`
- `object`
- `put`
- `close`

These are valuable but less urgent for first visible output.

## Backend Lowering

The same command IR should lower differently in each backend.

### HTML

For HTML, likely translations are:

- colors -> CSS color / currentColor / scoped style state
- transforms -> CSS transforms on wrapper spans/divs
- page background -> page block background styles
- `content`/`bop`/`eop` -> faithful overlay/underlay DOM fragments
- images -> `<img>` or embedded object wrappers
- annotations/destinations/outlines -> anchors, links, metadata, navigation UI

Low-level object graph commands may be ignored, recorded as metadata, or rejected
in HTML mode.

### PDF

For direct PDF output, the same command IR can lower much more directly:

- colors -> graphics state operators
- transforms -> graphics state transforms
- page content streams -> page content streams
- forms -> PDF XObjects
- images -> image XObjects or included PDF objects
- annotations/outlines/destinations -> native PDF objects
- document/object graph updates -> native PDF catalog/page/resource updates

### DVI

The DVI backend does not need to consume the command IR. It can continue to emit raw
special strings.

If desired later, the DVI backend may still parse for validation, but that is not
required by this design.

## Error Policy

The special parser should distinguish:

- unrecognized command
- recognized command with invalid syntax
- recognized command with valid syntax but unsupported lowering in the current
  backend

These three cases should not collapse into one generic error.

Suggested behavior:

- parsing failure: clear error with original special text
- unsupported command lowering: backend-specific error or warning
- ignorable command in a backend that does not care: explicit no-op, not silent
  parse failure

## State Model

Some specials are stateful and require backend-side stacks.

The IR consumer should maintain at least:

- current color stack
- current transform stack
- currently open breakable annotation stack
- currently open form definition stack
- page-scope background/content declarations

The parser itself should stay mostly stateless except for lexical parsing.

## Relationship To Existing Notes

- [04-html-output.md](04-html-output.md) depends on this note for graphics,
  color, image, and annotation handling.
- A future PDF backend should also depend on this note rather than inventing a
  separate special model.

## Open Questions

- How much of raw PDF marking stream syntax should be parsed beyond simple
  storage?
- Should `object` / `put` / `close` remain a shared command family, or live in a
  PDF-only extension layer?
- Should legacy compatibility specials be normalized into this same IR, or pass
  through adapter-specific shims first?
- Should page-level `bop`/`eop` content be represented as literal streams or as
  a later graphics AST?
