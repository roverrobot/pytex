# Reflow Backend

This note locks the intended architecture for a true reflow backend.

It is narrower than the broader HTML note. The key point here is not HTML as a
format, but the correct semantic input layer for reflow output.

## Main Point

A true reflow backend should not be driven by shipped pages or the output
routine.

It should consume the contribution stream of the outer vertical list before page
breaking and before page-local output-routine effects are turned into final page
structure.

In practice, the right hook is the explicit page-builder contribution step used
by the outer `VList`.

## Why Not The Output Routine

The output routine is the right place for page-faithful backends because it is
where TeX turns the contribution list into final pages and applies page-local
behavior such as:

- running heads and feet
- page numbers
- marks as used by page furniture
- page-local insert placement
- final `\box255` assembly

But these are mostly page concepts, not reflow concepts.

In a true reflow model:

- headers and footers are usually meaningless
- page numbers are usually meaningless
- marks are usually meaningless unless later reinterpreted as metadata
- output-routine page furniture should not be treated as primary document
  structure

So the output routine is the wrong semantic boundary for reflow.

## Why The Contribution Stream Is Better

The outer vertical list contribution stream is earlier than page building but
later than raw command execution.

That makes it a good reflow boundary because:

- paragraphs, display math, and alignments have already been recognized as real
  contributed objects
- the backend can inspect the `source` relationships of contributed nodes
- page splitting has not happened yet
- output-routine page furniture has not been imposed yet

This means the reflow builder sees semantically meaningful block contributions
without needing to reconstruct them from page fragments.

## Relationship To Page Building

The page builder and the reflow builder should be siblings, not one built on
top of the other.

The intended model is:

- the outer `VList` contributes nodes
- the page builder consumes those contributions for TeX-faithful page breaking
- the reflow builder consumes those contributions for semantic block flow

So reflow is not a variation of shipout.

It is a parallel consumer of the same contributed vertical material.

## Block Identity

The reflow builder should use the contribution boundary plus `.source`
provenance to recover higher-level block structure.

The important cases are:

- `Paragraph` -> paragraph block
- `DisplayMathNode` -> display-math block
- `HAlignment` / `MAlignment` -> table/alignment block
- contributed rules or separators -> structural separator blocks when useful
- whatsits/specials -> metadata or media hooks, depending on type

The contribution step is especially valuable because it sees these blocks before
page breaking can split them across pages.

## Paragraphs And Alignments

For true reflow, page splitting should not define block boundaries.

If a paragraph or alignment would later be split across pages in TeX's page
builder, that should not matter to the reflow backend. The reflow backend should
work from the pre-page-break contribution stream and preserve the original block
as one semantic unit.

This is one of the main reasons to avoid page-local shipout data as the primary
input for reflow.

## Inserts And Notes

`\insert` is semantically important for reflow because it represents anchored
content at the point where the note is introduced.

So for reflow:

- inserts should not be treated primarily as page-local footnote areas
- they should be treated as note-like anchored annotations in reading order

This is a semantic reinterpretation, not a page-faithful reproduction of TeX's
insert placement.

## Floats

Floats need separate treatment from notes.

The first reflow interpretation should be:

- preserve source order
- represent figures/tables as block-level media objects
- do not try to preserve output-routine page placement

Later work may add placement hints or float metadata, but that should not be
the initial model.

## Initial Reflow IR

The first reflow IR should stay small and block-oriented.

Suggested initial block kinds:

- `ParagraphBlock`
- `DisplayMathBlock`
- `AlignmentBlock`
- `MediaBlock`
- `NoteAnchor`
- `SeparatorBlock`
- `MetadataBlock`

This IR should represent semantic reading structure, not page geometry.

## Non-Goals

The reflow backend should not try to preserve:

- running headers/footers
- page numbers
- page-local mark behavior
- exact output-routine placement
- page geometry as such

Those belong to page-faithful output, not reflow.

## Short Version

The true reflow backend should:

- hook into outer-vertical-list contribution, not shipped pages
- ignore page-only output-routine furniture by default
- preserve semantic block structure in source order
- treat `\insert` as anchored note content
- treat floats as source-order block media, not page-positioned furniture
