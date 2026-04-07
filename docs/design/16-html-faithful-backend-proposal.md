# High-Fidelity HTML Backend Proposal

This note describes a possible high-fidelity HTML backend.

It is **not** the current implementation. The currently supported HTML output is
`html_reflow`, which is described separately in `15-html-reflow-backend.md`.

The purpose of this note is to describe a page-faithful HTML direction that fits
cleanly into the current architecture.

## Main Point

A high-fidelity HTML backend should be treated as a shipout backend, not as a
reflow renderer.

Its source of truth should be the final shipped pages after the output routine
has run. It should preserve page structure and visual layout as closely as
possible, while still reusing the existing parser, typeset, page-builder, and
shipout layers.

So the high-level pipeline would be:

1. normal parsing, expansion, and layout construction
2. normal page building and output routine
3. final shipped page boxes
4. shipout-time HTML page rendering

This is very different from `html_reflow`, which keeps the same runtime page
lifecycle but derives its final document from the outer vertical list's raw
owner history.

## Why Keep It Separate From Reflow

Reflow HTML and page-faithful HTML solve different problems.

### Reflow HTML

Reflow HTML is for:

- readable web articles
- semantic structure
- MathML and document-order rendering
- accessibility-oriented output
- later semantic export

### High-fidelity HTML

A faithful HTML backend would instead target:

- page-faithful journal or publisher output
- browser display that closely matches PDF
- page debugging and inspection
- direct reuse of page-level features such as page numbers and output-routine
  effects

These should remain separate products, not one backend with a formatting flag.

## Architectural Position

A faithful HTML backend belongs after the page layer and should be documented as
part of the shipout family.

It should therefore build on:

- the page builder and output routine
- the shared `Shipout` page walker
- the shared special IR where possible

This means it is much closer to the DVI and PDF backends than to `html_reflow`.

## Input To The Backend

The input should be the final shipped pages in shipout order.

More specifically, the backend should consume:

- the shipped page box passed to `shipout(...)`
- its nested `hlist` and `vlist` structure
- ordinary char, ligature, rule, glue, kern, and whatsit nodes
- source links where those are helpful, but not as the primary rendering source

The source of truth is the page that TeX actually shipped, not the raw main
vertical list.

## Page Model

Each shipped page should become an explicit page wrapper in the DOM.

A possible shape is:

```html
<section class="tex-page">
  <div class="tex-page-content">
    ...
  </div>
</section>
```

The exact tags are not important. The important point is that:

- pages remain explicit in the DOM
- page order remains explicit
- page-local material stays on the page where the output routine put it

Unlike `html_reflow`, a faithful backend should not merge content across pages
or discard page boundaries.

## Positioning Model

A faithful backend should render page content using positioned boxes.

That suggests a model such as:

- one positioned page wrapper with fixed dimensions
- nested absolutely positioned block containers for TeX boxes
- explicit positioned text runs
- explicit positioned rules and other visual elements

The backend does not need to reproduce TeX internals one-for-one in the DOM,
but it should preserve the final page geometry honestly enough that the visual
result stays close to the shipped page.

## Role Of The Shared Shipout Walker

The shared `Shipout` walker already knows how to:

- traverse shipped boxes recursively
- maintain shipout position
- visit chars, rules, and whatsits in the correct order
- interpret some specials through the special IR

A faithful HTML backend should reuse that machinery rather than inventing a
separate page traversal stack.

The backend-facing surface would therefore still look like shipout methods such
as:

- page start and end hooks
- font selection hooks
- positioned char output
- positioned rule output
- special and special-IR hooks

What changes is only the concrete lowering: instead of DVI bytecode or PDF
operations, the backend would emit DOM and CSS structures.

## Paragraph Handling

A faithful backend should not try to rebuild prose paragraphs from raw owner
history the way `html_reflow` does.

Instead, it should honor the page-fragment structure that TeX actually shipped.
That means:

- a paragraph that spans pages remains split across pages
- line boxes stay page-local
- page-local indentation and line breaks remain visible

Paragraph fragments can still use semantic HTML such as `<p>`, but only when
that does not destroy the actual shipped page structure. In many cases a more
neutral positioned block wrapper may be safer.

## Math Handling

Math is the hardest fidelity question.

For a page-faithful backend, the default source of truth should be the shipped
math boxes, not raw math owners.

That means a faithful HTML backend should be allowed to render math as:

- positioned glyph and box content
- faithful rule and delimiter geometry
- page-local equation labels

This is the opposite default from `html_reflow`, which prefers raw math owners
and MathML.

That said, a faithful backend could still opportunistically preserve some
semantic hooks, for example via `data-*` attributes or source references, but
those should not override shipped layout.

## Fonts

A faithful backend should preserve concrete font usage more directly than
`html_reflow`.

At minimum it should:

- keep actual TeX font identity available in the DOM or CSS
- map shipped chars to web-usable font resources when possible
- preserve concrete font-size and font-switch information accurately

This may require more web-font work than the current reflow backend, because
faithful positioned HTML cannot rely only on a simple serif/sans/mono role
model.

## Rules, Glue, And Kerns

Rules are naturally representable in faithful HTML as positioned rectangles or
bordered elements.

Glue and kerns should not usually become visible DOM nodes of their own.
Instead they should influence positioning and dimensions of surrounding boxes.

That is another reason the faithful backend should be built around shipped-box
geometry rather than around semantic block reconstruction.

## Inserts And Page Furniture

A faithful backend should preserve output-routine results rather than replacing
them with semantic reinterpretations.

That includes page-local material such as:

- footnote areas
- floats after output-routine placement
- running heads and feet
- page numbers
- other page furniture introduced by the output routine

This is one of the main reasons a faithful backend should consume shipped pages
rather than the raw vertical stream.

## Specials And Graphics

A faithful HTML backend should participate in the same special layer used by the
shipout family.

In particular:

- ordinary unrecognized specials can remain opaque or become metadata
- recognized `dvipdfm`-style specials should lower through the shared special
  IR where possible
- color, annotations, links, and object placement should be implemented in a
  way consistent with the shipout and special notes

This keeps HTML aligned with the PDF backend and avoids a one-off HTML graphics
model.

## Relationship To The Special IR

The special IR should remain a separate note.

A faithful HTML backend does not need its own private special language. Instead
it should consume the same typed special operations already introduced at the
shipout layer, then lower them into DOM, CSS, or browser-native constructs.

Examples include:

- color stack changes
- anchors and links
- image or PDF-like object placement
- later transform support if the shared special IR grows in that direction

## Relationship To Reflow HTML

The two HTML modes should stay clearly separate.

### Current reflow backend

- keeps the normal page lifecycle for compatibility
- derives final HTML from the outer vertical list's raw owner history
- prefers semantic paragraphs, tables, notes, and MathML
- intentionally ignores most page furniture

### Proposed faithful backend

- keeps the normal page lifecycle because it is part of the source of truth
- derives final HTML from shipped pages
- preserves page boundaries, page-local fragments, and page furniture
- favors concrete box and glyph layout over semantic reconstruction

## Implementation Direction

A reasonable staged path would be:

1. keep the current shared `Shipout` walker
2. add a new HTML shipout backend class beside DVI and PDF
3. emit explicit page wrappers and positioned box content
4. support chars, rules, and raw specials first
5. then add typed special handling for color, links, and placed objects
6. only later add more semantic source annotations if useful

This keeps the first implementation honest and close to the current codebase.

## Non-goals For The First Faithful Version

A first faithful HTML backend would not need to solve everything at once.
It could defer:

- semantic reflow
- MathML-first rendering
- accessibility-oriented restructuring
- cross-page paragraph merging
- a universal source-level semantic export layer

Those belong more naturally to `html_reflow` or later export-oriented paths.

## Short Version

A high-fidelity HTML backend should be treated as a proposed shipout backend
that:

- consumes final shipped pages
- preserves explicit page structure
- renders positioned boxes, text, rules, and page furniture
- participates in the shared special IR where possible
- stays separate from the current semantic `html_reflow` backend
