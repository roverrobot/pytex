# DVIPDFm Special IR

This note defines the current design for `dvipdfm`-style `\special` handling.

We only intend to support the `dvipdfm` `pdf:` family here. This is not meant
to be a generic note for all historical `\special` dialects.

## Main Point

`dvipdfm` specials should be treated as a small driver language that is compiled
at shipout time into backend-facing IR operations.

The boundary is:

1. raw `Special` node in the layout tree
2. `dvipdfm` compiler at shipout time
3. small backend IR methods
4. backend-specific lowering

This means:

- ordinary layout still uses the existing node/list/box IR
- `CharNode` already is the text IR and should not be wrapped in another
  character IR
- `Special` stays raw until shipout
- only recognized `pdf:` commands are lowered into typed backend operations

## Why This Boundary

By shipout time, most of the page is already concrete:

- characters are `CharNode`
- rules are rule nodes
- glue, kerns, lists, and boxes are already layout IR

The only thing that still needs interpretation is the payload of `\special`.

So the extra abstraction belongs exactly there: at the point where a raw special
string is emitted during shipout.

## Scope

This note covers only specials beginning with `pdf:`.

Everything else remains out of scope for now, including:

- `color ...`
- `psfile=...`
- HyperTeX
- TPIC
- raw `ps:`

Unknown or unsupported specials should remain opaque and flow through as raw
special strings.

## Pipeline

The intended execution path is:

```text
Special node text
  -> Shipout.special(text)
  -> dvipdfm compiler
  -> backend IR method calls
  -> backend-specific output
```

The base `Shipout` walker owns:

- traversal order
- page position
- glue and kern movement
- shifted box traversal
- whatsit dispatch

The `dvipdfm` compiler owns:

- recognizing `pdf:` specials
- normalizing command aliases
- parsing the small command envelope
- lowering recognized commands into backend IR calls

The backend owns:

- how those IR methods are realized in DVI, PDF, HTML, or future backends

## Why `Special` Stays Raw

The `Special` node is tied to TeX input syntax. It records that a
`\special{...}` occurred at a given point in the shipped page.

It should not be converted earlier into a backend-neutral node object because:

- specials do not participate in paragraph or box building the way characters do
- only some specials need structured interpretation
- different backends may support different subsets
- shipout is the first place with the right output-facing context

So the neutral IR belongs at the shipout boundary, not in the layout node.

## Compiler, Not Just Parser

The `dvipdfm` layer is best understood as a small compiler, not just a passive
parser.

That is acceptable because the base shipout walker already performs similar
lowering work for ordinary layout:

- tracking current position
- resolving glue movement
- traversing nested boxes

So if the `dvipdfm` layer later needs limited local state, that is consistent
with the rest of shipout.

## Syntax Front-End

The current compiler only needs a small syntax front-end.

### Command Name Parsing

The first token after `pdf:` selects the command.

Aliases should normalize immediately, for example:

- `ann` / `annot` / `annotate`
- `bc` / `bcolor` / `begincolor`
- `bt` / `btrans` / `begintransform`

The backend should not have to care about historical alias spellings.

### Named Argument Parsing

Many commands are naturally:

- a command name
- zero or more named arguments
- an optional trailing payload

For example:

```text
pdf: image @fig width 4.0in rotate 45 (figure.png)
```

should parse conceptually as:

- command: `image`
- optional name: `@fig`
- options:
  - `width 4.0in`
  - `rotate 45`
- source:
  - `(figure.png)`

The important named argument families are:

- dimensions: `width`, `height`, `depth`
- transforms: `scale`, `xscale`, `yscale`, `rotate`
- image boxes: `bbox llx lly urx ury`

The current code keeps payloads such as annotation dictionaries and file strings
mostly raw rather than building a full PDF-value AST.

That is deliberate. The first goal is to standardize the command envelope and
the backend operation boundary, not to build a full PDF object parser up front.

## Current Minimal Backend IR

The first concrete backend IR for `dvipdfm` specials is intentionally small:

- `rawSpecial(text)`
- `setColor(mode, space=None, values=None)`
- `annotate(kind, name=None, dimensions=None, payload=None)`
- `xObject(kind, name=None, options=None, source=None)`

This is enough for the current first subset:

- color stack commands
- fixed and breakable annotations
- XObject-like resource/image commands

## Raw Fallback

Unrecognized specials should stay opaque:

- non-`pdf:` specials
- unsupported `pdf:` commands
- malformed `pdf:` commands

Those should fall through to `rawSpecial(text)` unchanged.

This keeps the compiler incremental and low-risk.

## DVI As A Full Pipeline Consumer

The DVI backend should not bypass the IR for recognized `dvipdfm` commands.

Instead, DVI should:

- receive the backend IR calls
- reassemble them into `pdf:` special strings
- write them out as DVI specials

That is useful even though it looks a little indirect, because it tests the
whole path:

```text
raw special text
  -> dvipdfm compiler
  -> backend IR
  -> DVI reserialization
```

Unknown specials still pass through unchanged via `rawSpecial`.

## Color

Color is the simplest graphics-state family.

For `dvipdfm`, the input language distinguishes:

- `setcolor`
- `begincolor`
- `endcolor`
- `bgcolor`

The backend IR should keep these as semantic color operations rather than
pretending they are full graphics-state save/restore:

- `setColor("set", ...)`
- `setColor("push", ...)`
- `setColor("pop")`
- `setColor("background", ...)`

That keeps color stack meaning explicit.

## Transforms

Transforms are different from color.

`dvipdfm` transform commands are explicitly scoped and nested:

- `begintransform`
- `endtransform`

Because transform composition is cumulative, the future transform IR should not
collapse immediately into a single absolute "set transform" operation.

The preferred future transform IR is:

- `pushTransform()`
- `popTransform()`
- `concatTransform(matrix)`

This is better than a broad `saveState()` / `restoreState()` naming scheme,
because those names suggest a full graphics-state stack including color, line
width, clipping, and more. The current design only means transform scope.

This transform-specific naming lets:

- PDF map directly to `q`, `Q`, and `cm`
- HTML/CSS maintain its own transform stack and emit absolute transforms on
  nested wrappers

Color should remain a separate IR family from transforms.

## Command Families

The command families naturally split into two waves.

### First wave

These are practical and local enough to standardize first:

- color
- transform
- annotation
- XObject/image placement

### Second wave

These are useful, but less obviously part of the minimal page-graphics IR:

- destinations
- outline entries
- page content stream injection
- document info and catalog updates
- arbitrary PDF object creation and mutation
- article/thread support

These should wait until another backend actually wants them as structured
operations.

## Backend Lowering

The backend IR should describe what a backend must honor, not how the input
syntax spelled it.

Examples:

- `pdf: bc ...` lowers to `setColor("push", ...)`
- `pdf: ann ...` lowers to `annotate(...)`
- `pdf: image ...` lowers to `xObject(...)`
- future `pdf: bt ...` should lower to `pushTransform()` plus
  `concatTransform(...)`
- future `pdf: et` should lower to `popTransform()`

Backends then implement those operations in their own natural way.

### DVI

- recognized `dvipdfm` IR operations are serialized back into `pdf:` specials
- unknown specials are emitted unchanged

### Direct PDF

- colors become native PDF graphics-state color operators
- transforms become native scoped transforms
- annotations and XObjects become native PDF objects

### Faithful HTML

- colors become scoped style state
- transforms become wrapper-local transform state
- annotations and object placement become DOM/CSS structures or metadata

## Error Policy

The compiler should distinguish:

- unrecognized command
- recognized command with invalid syntax
- recognized command with valid syntax but unsupported backend lowering

Those should not collapse into one generic failure.

For the first pass, the practical behavior is:

- malformed or unsupported recognized commands fall back to raw passthrough
- backends may later choose to warn or error more explicitly

## Short Version

- only `dvipdfm` `pdf:` specials are in scope
- `Special` nodes stay raw until shipout
- `dvipdfm` specials are compiled at shipout time
- the first backend IR is small: raw special, color, annotation, XObject
- DVI should consume that IR and reserialize it back into `pdf:` specials
- transforms should later use `pushTransform`, `popTransform`, and
  `concatTransform`
- color and transform should remain separate IR families
