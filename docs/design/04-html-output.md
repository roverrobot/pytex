# HTML Output

This note locks in the first design for HTML output.

## Goals

- Support HTML as a first-class output target, not just as a debugging view.
- Keep room for two distinct HTML products:
  - page-faithful HTML for journal/web publishing
  - reflowable HTML for semantic reading and later export
- Reuse the existing TeX parser and node-building pipeline as much as possible.
- Avoid committing to `dvips` semantics. Graphics and color should follow a
  `dvipdfm`/`xdvipdfmx`-style special layer.

## Two HTML Modes

The engine should eventually support two separate HTML backends.

### Faithful HTML

Faithful HTML preserves page structure and visual layout as closely as possible.
Typical output will use page wrappers, positioned boxes, explicit rules, and
page-local footnotes.

This mode is useful for:

- journal publishing where PDF and web output should match closely
- page inspection and debugging
- direct reuse of page-level features such as page numbers and output-routine
  effects

### Reflow HTML

Reflow HTML prioritizes readable flow and semantic structure over exact layout.
It should prefer structural HTML such as paragraphs, tables, and MathML.

This mode is useful for:

- readable web articles
- accessible output
- later export paths that want semantic structure rather than page geometry

These are separate products, not one backend with a formatting flag.

## First Implementation Target

The first implementation target on the `html-reflow` branch is a page-aware
reflow mode.

It is "reflow" in the sense that line boxes on a page can be merged back into
paragraph fragments, but it still keeps explicit page boundaries and page-local
output-routine behavior.

This is the best first compromise because:

- page boundaries still matter semantically for footnotes and page numbers
- the final shipped page already reflects output-routine effects
- typeset nodes retain a `.source` pointer back to the originating raw node
- we can recover paragraph identity without throwing away page structure

## Input To The HTML Builder

For the first HTML mode, the input should be the final shipped pages collected
after the output routine runs.

This is not the raw pre-output body in `\box255`; it is the final page that is
actually passed to `shipout()`.

The raw main vertical list remains important for future purely semantic export,
but it is not the first source of truth for page-aware HTML.

The first builder should therefore consume:

- page boxes in shipout order
- their child boxes and nodes
- `.source` links from typeset nodes back to raw nodes

## Page Model

Each shipped page becomes one HTML page block.

Suggested shape:

```html
<section class="page">
  ...
</section>
<hr class="page-boundary">
```

The exact tags may change, but the model is fixed:

- pages are explicit in the DOM
- page numbers remain attached to the page that produced them
- page boundaries are rendered explicitly, for example by `<hr>`

## Paragraph Model

Paragraphs are reconstructed from page-local line boxes, grouped by their raw
paragraph source.

Important rule:

- a paragraph that spans pages becomes one paragraph fragment per page, not one
  giant paragraph merged across pages

So if the same raw paragraph source continues on the next page, the next page
gets a new HTML paragraph fragment.

Suggested output:

```html
<p class="indent">...</p>
<p class="noindent">...</p>
```

`<p>` is still the correct base element. Indentation is paragraph metadata and
should be represented through classes or equivalent styling.

## Inserts

For the first page-aware HTML mode, inserts are not handled as explicit `INS`
nodes.

By the time a page has passed through the output routine and is finally
shipped out, insert material has already been lowered into the page structure
chosen by that routine, for example footnotes, floats, and page-local note
areas.

So the first HTML builder should simply interpret the final shipped page. It
does not need a separate insert-placement algorithm of its own.

Future semantic HTML may still choose to bypass the output routine and recover
raw insert nodes directly.

## Block-Level Mapping

The first HTML builder should recognize at least these block-level cases:

- paragraph fragments
- display math fragments
- alignments
- explicit rules
- vertical boxes that matter structurally
- page-level whatsits and marks

Initial mapping goals:

- paragraphs -> `<p>`
- display math -> block math container, later MathML
- alignments -> `<table>`
- rules -> `<hr>` or styled block separators

## Node Handling Matrix

The first page-aware reflow builder needs to handle two layers at once:

- raw/source-level nodes recovered through `.source`
- low-level rendered nodes found inside shipped pages

The source node decides the semantic block. The rendered nodes provide the page
fragment content.

### Source-Level Nodes

| Source node | First HTML handling |
| --- | --- |
| `Paragraph` | Rebuild one page-local paragraph fragment. Merge all line boxes on the same page whose `.source` points to the same raw paragraph. Render as `<p>` with paragraph classes such as `indent` or `noindent`. |
| `DisplayMathNode` | Render as one block math fragment. Keep equation number placement as page-local metadata. Initial HTML can use a placeholder math container; later this should become MathML. |
| `HAlignment` | Render as `<table>`. Preserve row and cell grouping from the aligned material instead of flattening it into paragraphs. |
| `Mark` | Treat as metadata, not visible page content, unless a later backend explicitly wants running-head or navigation information. |
| `VAdjust` / `ADJUST` | In TeX terms this is migratory vertical material that belongs with the enclosing vertical list, not ordinary inline text. For the first page-aware HTML mode, ignore `ADJUST` when it arises from paragraph lines, since line-spacing adjustments are not expected to transfer consistently to browser reflow. Outside paragraph fragments, it may later be attached to the current page block if it has visible content. |
| `Special` / `WHATSIT` | Route through a `dvipdfm`/`xdvipdfmx` special parser. Unknown specials are ignored or recorded as metadata; known specials later produce color, graphics, anchors, and similar effects. |

### Rendered Node Types

| Rendered node type | First HTML handling |
| --- | --- |
| `HLIST` | Usually a line box or inline box container. Inside a paragraph fragment, flatten into inline content. Outside paragraphs, recurse and render as a block or inline container depending on the source node. |
| `VLIST` | Block container. Recurse into children. When it comes from page-level structure, render as a nested block group rather than as a paragraph. |
| `CHAR` | Append text to the current inline run. |
| `LIGATURE` | By default, emit the underlying source characters, not the rendered ligature glyph. Let the browser and the chosen web font form ligatures visually. Fall back to the rendered ligature glyph only when exact glyph fidelity is required. |
| `GLUE` | Convert to ordinary spaces or block separators depending on context. Interword glue inside paragraph lines usually becomes a normal space. |
| `KERN` | Usually ignore exact dimensions in reflow mode. Optionally preserve significant spacing as CSS letter-spacing or margin hints when needed. |
| `RULE` | Render as `<hr>` for block separators, or as a styled inline/block element when it is not acting like a page or section rule. |
| `MATH` | In page-aware reflow, use this as part of math fragment reconstruction. Inline math should become an inline math container; display math should be handled through the `DisplayMathNode` source. |
| `DISC` | Treat as a line-breaking hint only. Emit the replacement text unconditionally in reflow HTML, and do not preserve TeX's chosen discretionary break glyph placement. This lets the browser do its own line breaking without leaving a discretionary hyphen stranded in the wrong place. |
| `MARK` | Ignore visually; keep only as metadata. |
| `ADJUST` | Do not treat as normal paragraph text. In the first HTML mode, ignore paragraph-line `ADJUST` nodes. If a later mode wants more fidelity, non-paragraph `ADJUST` content can be attached to the enclosing page block. |
| `WHATSIT` | Delegate to special handling. Non-special whatsits may initially be ignored if they have no visible HTML effect. |
| `PENALTY` | Ignore in HTML output. It affects breaking but has no direct visual representation. |

### Node Types Expected To Be Rare Or Already Lowered

Some node shapes should not need dedicated first-pass HTML handling because they
are already lowered before page-aware rendering:

- `Paragraph` line-breaking internals are expected to appear as ordinary line
  boxes, glue, kerns, and text nodes.
- explicit `INS` nodes are not expected in the first HTML mode because shipped
  pages already reflect output-routine insert placement.
- `ADJUST` is migratory in TeX, but paragraph-line adjustment material is
  intentionally ignored in the first HTML mode.
- accent constructions are usually represented through the final rendered boxes
  and characters, not through a separate HTML-only accent node.
- `UNSET`-style alignment intermediates should normally not survive to shipped
  page output; if they do, the HTML builder should treat that as an internal
  fallback case and recurse into children conservatively.

## Inline-Level Mapping

Inside paragraph fragments, the builder should handle:

- characters and ligatures as text runs, with ligatures usually expanded back to
  their source characters for copy/paste, search, and accessibility
- discretionary nodes reduced to their replacement text, since browser line
  breaking may differ from TeX line breaking in reflow mode
- kern and ordinary interword glue as spacing hints
- inline math as inline math containers
- inline boxes as nested spans when they matter structurally

The first reflow mode should not try to preserve every TeX spacing dimension
exactly. It only needs enough information to recover readable flow while still
following the page fragment structure.

## Math Handling

Math is the hardest part of reflow HTML.

The source of truth for math should remain the raw math nodes, not the final
shipped glyph arrangement alone. However, raw TeX math is still not purely
semantic: TeX allows boxes inside math, and those boxes may contain arbitrary
material.

So the first design should use a mixed strategy:

- recover semantic math structure when it is clearly present
- allow box-based fallback when the content is too TeX-specific
- do not require every math subtree to become pure MathML

### Math IR Policy

The math conversion layer should build a math IR that is richer than MathML.

It should have:

- semantic nodes for ordinary math structure
  - symbols
  - scripts
  - fractions
  - radicals
  - delimiters
  - matrix/table-like constructs
- box/layout fallback nodes for arbitrary TeX box content

This lets the renderer target:

- MathML when the subtree is representable
- HTML/CSS fallback when the subtree depends on arbitrary TeX box layout

### Arrays And Matrices

LaTeX array-like math environments are commonly lowered into a `vbox`
containing a `halign`.

This is acceptable for the first reflow mode:

- the outer `vbox` can be treated as a structural holder
- the inner `halign` still exposes rows and cells
- the raw cell boxes are enough to reconstruct a matrix/table-like structure

So normal matrices should still be translated to MathML-style table structure,
for example an `mtable`-equivalent in the math IR.

### Extra Material Inside Math Boxes

The difficult case is extra non-matrix material placed inside math boxes.

TeX does not prevent users from building complex layouts inside a math `vbox`,
including arbitrary boxes and additional nodes around an alignment.

For the first reflow mode:

- harmless extra box noise may be ignored
- regular alignment-shaped content should still be recognized as a matrix/table
- irregular content should fall back to opaque boxed math rendering

The first reflow mode does not guarantee 100% compatibility with arbitrary TeX
box programming in math.

### MathML Boundary

MathML is the preferred target for representable math structure, but it is not
the only target.

The engine should not force arbitrary TeX math layout into pure MathML. When a
subtree is too box-oriented or irregular, the renderer may keep it as a boxed
HTML/CSS math fragment instead.

## Graphics, Color, and Specials

Graphics and color should not be designed separately for HTML and PDF.

Instead, the engine should eventually parse `dvipdfm`/`xdvipdfmx` specials into
a small shared IR. Then:

- faithful HTML can render that IR into DOM/CSS
- direct PDF output can render the same IR into PDF operations
- DVI output can keep emitting raw specials unchanged

This avoids a `dvips` dependency and avoids the need for a PostScript
interpreter.

## Deferred Work

- Fully semantic reflow directly from the raw main vertical list.
- Paragraph reconstruction across pages for non-faithful modes.
- Footnote/endnote policy for semantic HTML.
- MathML generation.
- Shared special IR for color, graphics, and image inclusion.
- A direct PDF backend that reuses the same graphics/special layer.
