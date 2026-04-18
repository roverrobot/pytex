# Reflow Document IR

This note proposes a common document-structure IR for reflow-oriented backends.

It sits above the current shipout IR and below backend-specific emitters such
as `html_reflow`. The goal is to let reflow backends keep TeX shipout semantics
while building a more structured document model than the current ad hoc
`Paragraph` collector.

## Main Point

The current reflow layer is too thin.

Today `reflow.py` mostly recognizes:

- vertical block grouping
- paragraphs
- text runs
- inline math
- inline boxes

That is enough for readable text, but not enough for stateful or structural
shipout operations such as:

- color changes
- hyperlink begin and end markers
- named destinations
- inline and block media
- future richer prose or DOCX lowering

So the proposal is:

1. keep `typeset.shipout.Shipout` as the shared page walker and whatsit
   dispatcher
2. make `reflow.Reflow` a document builder rather than a thin HTML helper
3. define a small common document IR with explicit levels
4. let `html_reflow` and future reflow-style DOCX output consume that IR

This keeps the current `Special.output(...) -> Shipout.special(...)` path while
giving reflow a place to attach those operations to a real document structure.

## Why This Is Needed

Not every shipout-time operation wants the same treatment.

Some operations are style changes and are easiest to handle while building
inline content:

- font-aware text runs
- color changes

Other operations are structural and must be inserted at the current logical
document location:

- link begin and end
- destination anchors
- figures or included media

The current `Paragraph`-only abstraction makes this awkward. It encourages
either:

- early interpretation in backend-specific paragraph-building code, or
- late deferral hacks that still do not have a clear structural target

The proposed IR solves that by making the current document position explicit.

## Relationship To Shipout IR

This note does **not** replace the shipout IR note.

The boundary remains:

```text
packed page box
  -> Shipout recursive traversal
  -> whatsit dispatch through node.output(...)
  -> reflow builder operations
  -> reflow document IR
  -> HTML or DOCX-style emission
```

So:

- `Shipout` still owns page walking
- `WhatsIt.output(...)` still owns execution of file ops and specials
- `DVIPDFmSpecialParser` still lowers recognized `pdf:` specials into typed
  callbacks
- `Reflow` becomes the place where those callbacks mutate a structured document

This is intentionally different from the DVI and PDF backends, which lower
shipout directly into a concrete page-output device.

## Proposed IR Levels

The common structure should be as close as practical to TeX shipped-page
structure while still being usable by HTML and DOCX emitters.

The proposed levels are:

- `Document`
- `Page`
- `Region`
- `Block`
- `Inline`

### `Document`

The document is the root and owns:

- document lifetime
- document-wide resources
- an ordered list of pages

Resources are things such as:

- registered fonts
- named images or external media
- future shared style or metadata tables if needed

### `Page`

A page corresponds to one shipped page in TeX.

It owns:

- page-local region containers
- page order within the document

The IR keeps pages even if some emitters flatten them later.

### `Region`

A page contains a fixed set of logical regions:

- `header`
- `body`
- `footer`

This is deliberately small.

Margin regions are out of scope for now. TeX does not have a general anchored
margin-note model that we need to preserve here.

### `Block`

A region contains ordered block nodes.

Initially the block layer should include:

- `ParagraphBlock`
- `DisplayMathBlock`
- `AlignmentBlock`
- `FigureBlock`
- `BlockBox`

`BlockBox` is the escape hatch for vertical material that behaves like a block
but is not yet given a more semantic block type.

### `Inline`

Inline content lives inside paragraph-like blocks.

Initially the inline layer should include:

- `TextRun`
- `InlineMath`
- `InlineBox`
- `Link`
- `Anchor`
- `InlineImage`

`TextRun` should carry a style state, not only raw text.

## Builder Model In `Reflow`

`Reflow` should manage the document IR and maintain a stack of active levels.

It already maintains `box_stack` for TeX boxes. The proposal adds:

- `doc_stack`
- inline style state
- any small mark stacks needed by specials, for example link begin/end nesting

### Stack Discipline

The stack is expected to follow this shape:

```text
Document
  -> Page
    -> Region
      -> Block
        -> Inline container
```

Not every operation can be applied at every level.

When an operation is not supported by the current node, `Reflow` should:

1. flush pending inline state if needed
2. close or fold the current node
3. pop to the nearest enclosing level that can accept the operation
4. perform the operation there
5. optionally reopen an inline context when subsequent content requires it

This is similar in spirit to TeX's own list-stack discipline.

## Proposed Basic Builder Operations

The builder surface should be expressed in terms of document structure, not in
terms of HTML elements.

### Document level

- `beginDocument()`
- `endDocument()`
- `defineResource(kind, key, payload)`
- `beginPage(page_box=None)`
- `endPage()`

### Page level

- `beginRegion(kind)`
- `endRegion()`

### Region level

- `appendBlock(block)`
- `beginParagraph(...)`
- `endParagraph()`
- `beginDisplayMath(...)`
- `endDisplayMath()`
- `beginAlignment(...)`
- `endAlignment()`
- `appendBlockBox(box, ...)`
- `appendFigure(...)`

### Inline level

- `appendText(text, style)`
- `appendSpace(width, style)`
- `appendInlineMath(node, collection, left_kern, right_kern)`
- `appendInlineBox(box)`
- `beginLink(target, metadata=None)`
- `endLink()`
- `appendAnchor(name)`
- `appendInlineImage(...)`
- `setStyle(delta)` or narrower operations such as `setColor(...)`

The exact method names can change. The important point is that these are common
document-building operations rather than backend-specific HTML helpers.

## Mapping From Existing Shipout Callbacks

The current shipout-facing callback family already gives almost all of the
semantic triggers the builder needs.

### `open()` / `close()`

These should correspond to:

- `beginDocument()`
- `endDocument()`

In a reflow backend, `close()` is where the final emitter serializes the built
document IR.

### `begin_page(box)` / `end_page(box)`

These should become:

- `beginPage(box)`
- `endPage()`

The builder should then open the relevant page regions, typically at least the
body region.

### `define_font(font)`

In reflow, this is primarily a resource registration event, not a stream-time
font switch.

That means:

- the builder may register the backend font as a document resource
- active font on text still comes from the character or text-run content
- HTML web-font registration is one lowering of that resource

### `select_font(font)`

This can remain a no-op or a compatibility hook for reflow.

Unlike DVI or PDF, reflow text generally carries its font identity directly on
the character or run source.

### `setColor(...)`

This is an inline style operation.

It should:

1. flush the current text run
2. update the current style state or color stack
3. let subsequent text runs inherit the new style

### `annotate(...)`

This is primarily a structural inline operation.

It should map to:

- `beginLink(...)`
- `endLink()`
- fixed-position markers where appropriate

The current special parser continues to normalize the outer `dvipdfm` command
family. The builder decides where in the document structure the link lives.

### `rawSpecial(text)`

Only a small fallback subset should become document-structure operations.

The important current case is:

- `pdf: dest (...)` -> `appendAnchor(name)`

Unknown raw specials may still be ignored or recorded as hidden metadata by the
final emitter.

### `xObject(...)`

This should become either:

- an inline image-like node, or
- a block figure-like node

The choice depends on the current document context, not on HTML-specific logic.

## HTML Lowering

HTML does not naturally preserve TeX page structure as visible pages in the
current reflow backend.

That is acceptable.

The proposed lowering is:

- `Document` -> one HTML document
- `Page` -> logical container only, usually flattened
- `Region(body)` -> contributes normal flow content
- `Region(header/footer)` -> currently empty or ignored in `html_reflow`
- `ParagraphBlock` -> `<p>` or block `<div>`
- `DisplayMathBlock` -> block MathML container
- `AlignmentBlock` -> table-like HTML structure
- `TextRun` -> text or `<span>`
- `Link` -> `<a>`
- `Anchor` -> element with `id`
- `FigureBlock` / `InlineImage` -> HTML media elements

So HTML may flatten page structure while still consuming the same common IR.

## DOCX Lowering

DOCX does not expose TeX pages directly as first-class page objects, but it does
have a document model with:

- document-level resources and settings
- headers and footers
- paragraph-like blocks
- runs and inline objects

So the same IR should still be useful.

In particular:

- `Region(header)` and `Region(footer)` map naturally to header and footer
  stories
- paragraph and inline structure is directly useful
- richer inline style state is more useful to DOCX than the current
  HTML-oriented `Paragraph` helper

This note does **not** require the current faithful DOCX backend to switch
immediately. It only defines a common target that DOCX-style reflow output can
grow toward.

## Non-Goals

This proposal does not try to:

- replace the current shipout IR for page-faithful backends
- invent a full CSS-like style system
- preserve exact TeX page geometry in HTML
- solve arbitrary unsupported specials
- introduce a generic margin-note anchoring system

It is a structural IR for readable, document-order reflow output.

## Migration Plan

The intended incremental path is:

1. define the document IR classes in `reflow.py`
2. make `Reflow` build that structure using a `doc_stack`
3. keep `Shipout` and `WhatsIt.output(...)` as the execution path for specials
   and file operations
4. move color, links, anchors, and media insertion onto builder operations
5. make `html_reflow` lower the built document IR instead of owning the
   structure itself
6. optionally let future DOCX-style reflow lowering consume the same IR

This keeps the current compatibility story while improving the abstraction
boundary.

## Open Questions

The main questions still to settle are:

- whether `FigureBlock` and `InlineImage` are both needed initially, or whether
  one media node with a display flag is enough
- how much inline style state should be normalized in the IR versus stored
  backend-neutrally as attributes
- whether page regions should be created eagerly for every page or lazily only
  when content appears
- whether alignments should start as one generic block kind or distinct table
  and math-alignment blocks

Those can be resolved during implementation without changing the main boundary:

- `Shipout` dispatches
- `Reflow` builds structure
- concrete reflow backends emit from the common document IR
