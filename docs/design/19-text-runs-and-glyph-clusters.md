# Text Runs And Glyph Clusters

## Status

This note locks the design for the base horizontal-text refactor that will
precede HarfBuzz-backed OpenType shaping and the final U+0020 spacing work.
It is a proposal until the migration described below is complete.

This is an engine-wide list-construction design. It is not part of the XeTeX
module. XeTeX intercharacter tokens affect which material reaches an `HList`,
but the resulting text-run and glyph-cluster machinery is shared by every
engine.

## Decisions

The design is based on the following decisions.

1. `GlyphCluster` is the generalization and eventual replacement of the current
   `Ligature` node.
2. A cluster is one indivisible horizontal layout unit. It may contain one
   glyph, several glyphs, automatic kerns, and horizontally or vertically
   shifted boxes.
3. A cluster keeps its logical source characters independently of its concrete
   glyph layout. Hyphenation and reflow consume the logical source, never infer
   text from glyph IDs.
4. Consecutive text is accumulated transiently by `HList` and shaped by the
   selected font backend. There is no durable `TextRun` node in a concrete
   horizontal list.
5. TFM fonts retain TeX ligature/kern-program behavior behind the common shape
   interface. OpenType fonts use HarfBuzz behind the same interface.
6. Fixed-layout output and reflow output deliberately consume different sides
   of a cluster:
   - DVI, XDV, PDF, SVG, and other page-faithful outputs use the TeX-realized
     boxes, advances, kerns, and vertical shifts.
   - HTML and DOCX recover Unicode text and font/feature information, then let
     the browser or word processor apply the font's GSUB/GPOS tables. They do
     not replay TeX's positioned glyph layout.
7. Text direction is outside this refactor. Source order is logical order and
   the first implementation shapes horizontal left-to-right runs. The source
   and layout split must not prevent a later direction-aware implementation.

The resulting flow is:

```text
characters and U+0020
        |
        v
XeTeX intercharacter insertion
        |
        v
HList pending text run --> FontBackend.shape(...)
        |                         |
        |                         v
        |                  GlyphCluster nodes
        |                   /              \
        v                  v                v
 non-text nodes     fixed-layout boxes   logical Unicode text
                    DVI/XDV/PDF/SVG      HTML/DOCX native shaping
```

## Terminology And Data Model

The model separates logical input, output glyphs, and layout units.

### Logical character (`TextChar`)

A `TextChar` record represents one Unicode scalar value presented to
horizontal text processing. It records at least:

- `char`: the Unicode character
- `font`: the selected `Font`, including its size and shaping features
- `word_char`: the word/boundary classification needed by TFM ligature
  programs, captured from the horizontal state when the character is appended
- `interword_glue`: `None` for ordinary characters; for U+0020, the interword
  glue calculated when the space was appended

The glue snapshot is necessary because `\spacefactor`, `\spaceskip`,
`\xspaceskip`, and font parameters may change before a pending run is flushed.
A logical character is source material, not a shipped glyph and not a box.

The initial migration may adapt current `CharNode` inputs into this record at
the `HList` boundary. Long term, cached `Font.__getitem__` nodes must not be used
as mutable source records.

### Glyph

A `Glyph` is the fixed-layout output primitive for exactly one font glyph. It
contains the selected font and the backend glyph identity needed by shipout.
For a TFM/DVI font this includes the engine character slot; for OpenType it may
include a glyph ID and glyph name.

A glyph does not claim a one-to-one Unicode mapping. Its logical meaning comes
from its containing cluster.

It has its own `NODE_TYPE.GLYPH`. The existing `CharNode` remains as the
character-addressed compatibility primitive while consumers migrate.

### Glyph cluster

A `GlyphCluster` is an indivisible `Box` in its parent horizontal list. It has
two required parts:

- `source`: the non-empty sequence of logical characters represented by the
  cluster, in logical order
- `list`: the already-realized fixed-layout contents, made from glyphs,
  automatic kerns, and packed/shifted boxes

It has its own `NODE_TYPE.GLYPH_CLUSTER`; it is not exposed to its parent as a
general `HLIST`. The shipout walker may traverse its contents like a packed
horizontal box, while the paragraph builder still recognizes it as an
indivisible text unit.

Its dimensions have the usual TeX meaning:

- `width` is the cluster's horizontal advance
- `height` and `depth` enclose the vertically positioned child boxes

Ink may overhang the advance. A zero-advance combining mark can therefore
increase height or depth without increasing width.

Every shaped character in a concrete `HList` is represented through this
contract, including the ordinary one-character/one-glyph case. This avoids
making all later consumers repeat `CHAR` versus `LIGATURE` special cases. Bare
glyph primitives occur inside cluster layout; they are not independent text
items in the parent `HList`.

The current forms map into the new node as follows:

| Case | Logical source | Fixed cluster contents |
|---|---|---|
| ordinary character | one character | one glyph |
| TFM ligature | several characters | one glyph |
| multiple substitution | one or more characters | several glyph boxes |
| combining mark | base and mark characters | glyph boxes with vertical and possibly horizontal shifts |
| TeX text accent | semantic accent/base source | accent and base boxes with the existing TeX positioning |

Automatic pair kerns may remain concrete automatic `Kern` nodes between
clusters. A backend may instead express positioning by changing glyph advances
inside clusters when that is the natural form of its shaping result. The line
breaker must support both representations.

### Source versus ownership

For `GlyphCluster`, `.source` has one meaning only: the logical characters that
can be reshaped or emitted as text. It is not the raw-list owner link currently
stored in `.source` on several other node kinds.

During migration, non-text nodes may keep the existing ownership convention.
If a cluster itself needs an owner/provenance link, that link is stored as
`.owner`. Reflow and hyphenation must not guess whether
`GlyphCluster.source` means characters or ownership.

## Fixed-Layout Cluster Construction

Font shaping returns glyph identities, source ranges, advances, and offsets.
The base text-layout layer lowers those results into ordinary TeX boxes before
the clusters enter the concrete `HList`.

Each positioned output glyph is represented by a fixed-width placement box:

- the placement box width is the shaped horizontal advance
- horizontal offset is represented inside the box without changing that
  advance
- vertical offset is represented by a shifted child box
- the child's ink dimensions contribute to the placement box's height/depth

The cluster contains those placement boxes in output order, plus automatic
kerns where appropriate. This representation can express HarfBuzz's one-to-one,
many-to-one, one-to-many, and many-to-many results without giving the shipout
backend a second positioning algorithm.

This also supplies the intended foundation for `\accent`: its current sequence
of a leading kern, shifted accent box, compensating kern, and base glyph can be
contained by one cluster and treated as one horizontal unit. Moving `\accent`
onto this representation is a follow-up, not a prerequisite for the first text
shaping migration.

## Font Shaping Contract

The common operation is conceptually:

```python
Font.shape(source, *, left_boundary=False, right_boundary=False)
```

`Font` supplies size and selected features and delegates to its
`FontBackend`. The backend-neutral result stream contains:

- `ShapedCluster`: a logical source range and one or more `ShapedGlyph` records
- `ShapedGlyph`: glyph identity, horizontal advance, and horizontal/vertical
  offsets
- `ShapedKern`: an automatic adjustment between clusters, including the source
  pair that caused it for tracing/debugging

`ShapedCluster` source ranges must partition the shaped logical characters
without reordering them in this first left-to-right implementation.
`ShapedKern` references source but does not consume it.

The backend boundary is responsible for font-specific shaping rules:

- `TFMBackend` runs the existing TeX ligature/kern and boundary programs.
- `OpenTypeBackend` passes the full run, font features, and boundary context to
  HarfBuzz and returns HarfBuzz cluster mappings and positions.
- the null/fallback backend produces one simple cluster per character.

The backend returns shaping information; the base text-layout code owns its
conversion into engine nodes and boxes. This keeps `FontBackend` independent of
live parser lists and keeps fixed-layout lowering shared by all fonts.

The existing OpenType conversion of selected GPOS pairs into TFM-style kern
programs is transitional. It should be removed once HarfBuzz shaping covers the
same path, so the same adjustment is not applied twice.

## HList Run Accumulation

`HList` owns one transient pending text run. A run contains adjacent logical
characters with compatible shaping context. U+0020 is text input and does not,
by itself, flush the run.

The processing order for an append is:

1. run the existing XeTeX intercharacter-class transition logic
2. append any material produced by the intercharacter token list normally
3. update `\spacefactor` or snapshot/reset interword spacing state as required
4. add the logical character, including U+0020, to the pending text run
5. shape only when the run reaches a materialization boundary

Starting or resuming an intercharacter token list is not itself a shaping
boundary. If the inserted tokens produce characters, those characters can join
the surrounding run. If they produce a kern, glue, box, font change, or another
non-text item, normal append processing flushes the run before that item.

A pending run is flushed before:

- appending a non-text node
- changing font or any shaping feature/context
- closing the `HList`
- exposing concrete contents through iteration, indexing, length, raw/concrete
  accessors, packing, serialization, or tracing
- mutating already-realized contents through operations such as `pop`, delete,
  replacement, `clear`, `\unskip`, or last-item accessors

After a flush, the pending source is empty and the concrete list alone is the
authoritative fixed-layout state. Pending run state is runtime-only and is
never serialized.

## U+0020 And Interword Glue

Space resolution happens after shaping, not before it.

When U+0020 is appended, `HList` snapshots `parser.interwordGlue()` in its
logical source record, resets the horizontal spacing state as TeX requires,
and leaves U+0020 in the run presented to the font backend.

After shaping:

- if a U+0020 remains an independent, one-character cluster, it is replaced by
  the glue snapshot associated with that source character; the generated glue
  retains the `TextChar` as `.text_source`
- if U+0020 shares a cluster with other source characters, it was consumed by
  shaping and the glyph cluster is retained; no interword glue is added for it

Any positioning adjacent to an independent space must survive the conversion,
either in neighboring advances or as automatic kerns. In particular, an
adjustment carried by the shaped space advance must be separated from the
discarded glyph advance before the cluster is replaced by glue. Detailed
spacing tests will be added in the dedicated spacing implementation slice.

## Line Breaking And Hyphenation

Normal line breaking treats `GlyphCluster` as one box with its reported
dimensions. It does not inspect or split the cluster's fixed-layout contents.

Hyphenation is the exception because it works in logical character space. The
paragraph typesetter must replace the current `CHAR`/`LIGATURE` branches with a
small generic text-source protocol:

- obtain logical characters from a cluster
- concatenate compatible cluster sources into a candidate word
- map hyphenation points back to source offsets
- reshape the affected left and right fragments with their new boundary
  context

A break inside a many-character cluster never slices the existing glyph list.
Both fragments are reshaped from source. This preserves ligature and kerning
behavior at the new line boundary and works equally for TFM and HarfBuzz.

Discretionary `pre`, `post`, and replacement text is also shaped through the
same base `HList` path. Automatic kerns remain discardable/transparent in the
same places where the current paragraph code treats them that way.

## Fixed Layout Versus Reflow

The two output families intentionally have different rendering contracts.

### DVI, XDV, PDF, and SVG

Fixed-layout backends consume the concrete cluster layout. The shared shipout
walker descends the cluster's boxes and kerns, emitting primitive glyphs at the
positions already decided by TeX's shaping/layout layer.

These backends must not rerun GSUB or GPOS. Doing so would double-apply
substitution or positioning and would make shipped geometry disagree with line
breaking.

### HTML and DOCX reflow

Reflow backends consume logical text, not the concrete cluster glyph list. They
join adjacent compatible cluster sources into Unicode text runs and carry
forward the selected font, language, and OpenType feature settings.

An interword glue node with `.text_source` contributes its U+0020 back to such
a run; it is not treated like explicit `\hskip` material. This lets the native
renderer see the same text, including spaces, that was originally offered to
the font shaper. Explicit glue without `.text_source` remains explicit layout
material.

The browser or DOCX rendering engine then shapes those runs using the embedded
or selected OpenType font. In particular, reflow output does not emit:

- backend glyph IDs
- TeX-generated automatic kern nodes that merely realize GPOS
- per-glyph horizontal or vertical offsets from the fixed layout

Explicit TeX structure that is not ordinary font shaping, such as boxes,
manual kerns, math, and an explicit `\accent`, remains represented by its raw or
semantic source and is handled by the reflow layer's existing structural rules.
Where an accent can be represented as Unicode base-plus-combining-mark text,
the native renderer may apply GPOS; otherwise the reflow backend keeps its
explicit semantic fallback.

This split means reflow output is not expected to reproduce TeX line breaks or
fixed glyph coordinates. It is expected to preserve logical text and request
the same font behavior from its native renderer.

## Module Boundaries

The durable text-layout data structures belong in a neutral base module, for
example `pytex/glyph.py`. That module must not import `hmode` or an engine module.

The responsibilities are divided as follows:

- `pytex/glyph.py`: `TextChar`, glyph, cluster, and shaping-result data
- `pytex/font_backend.py`: common shape operation and backend-neutral result
  contract
- `pytex/tfm.py`: TFM ligature/kern shaping implementation
- `pytex/opentype.py`: HarfBuzz shaping implementation
- `pytex/hmode.py`: intercharacter ordering, pending-run ownership, spacing
  snapshots, flush/materialization, and append semantics
- `pytex/typeset/paragraph.py`: source-based hyphenation and fragment reshaping
- `pytex/typeset/shipout.py`: fixed-layout cluster traversal
- HTML/DOCX reflow code: source-text run recovery and native shaping requests

Dependency direction matters. In particular, the new data module must not
reintroduce an eager `box -> hmode -> box` import cycle. Construction helpers
that require full box classes should use a lower-level representation or a
carefully placed local import.

## Migration Plan

The refactor will be implemented and committed in independently tested slices.

1. Add the neutral glyph/cluster data model and compatibility helpers without
   changing `HList` behavior.
2. Generalize paragraph word collection, hyphenation, discretionary handling,
   and fragment reshaping to the cluster source protocol.
3. Teach packing, tracing, serialization, fixed shipout, and reflow source
   recovery about clusters while retaining current `CharNode`/`Ligature` input.
4. Move current TFM ligature/kern realization behind the common shape
   interface and emit clusters.
5. Add the transient `HList` run accumulator and all materialization barriers.
6. Add HarfBuzz shaping for OpenType and remove the transitional GPOS-to-TFM
   kern-program path.
7. Complete U+0020-to-glue resolution after shaping.
8. Move text accents onto cluster composition once the common representation is
   stable.

Compatibility aliases may temporarily preserve `Ligature` and
`NODE_TYPE.LIGATURE` for old tests or serialized material, but new concrete text
must converge on `GlyphCluster`. Compatibility code is removed after all
consumers use the new protocol.

## Verification Requirements

Each implementation slice needs focused tests plus the full suite. The complete
refactor must cover at least:

- one character to one glyph
- several characters to one ligature glyph
- one character to several glyphs
- several characters to several positioned glyphs
- positive and negative pair kerns
- zero-advance and vertically shifted marks
- TFM left/right boundary programs
- an independent U+0020 becoming the glue snapshot
- U+0020 consumed as part of a cluster without extra glue
- font/non-text/list-inspection run flushes
- XeTeX intercharacter tokens executing before run accumulation
- hyphenation at a cluster boundary and inside a ligature cluster
- reshaping of discretionary pre/post/replacement fragments
- fixed-layout shipout using cluster boxes without reshaping
- HTML/DOCX emitting logical Unicode text without fixed glyph offsets
- serialization round trips for realized clusters only
- clean-interpreter imports of `box`, `hmode`, the new glyph module, and reflow
  backends

## Non-Goals

This design does not add:

- bidirectional text or vertical text direction
- script itemization across multiple fallback fonts
- a durable glyph-run node
- reflow reproduction of TeX's fixed line and page breaks
- HarfBuzz shaping inside HTML or DOCX generation

Those can be added later without changing the central contract: logical source
is retained for reshaping and reflow, while fixed output consumes the concrete
box layout already produced by TeX.
