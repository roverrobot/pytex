# Layer Separation

This note summarizes the layer split we want around TeX execution, layout
construction, shipped pages, and later export.

The immediate motivation is architectural clarity. The current "parser" works,
but it is doing several jobs at once:

- scanning text under mutable catcodes
- expanding tokens and dispatching commands
- mutating execution and layout state
- constructing nodes, lists, boxes, and math structures

That makes it hard to choose one clean IR boundary for every backend.

## Main Conclusion

There should not be one universal IR for all output backends.

TeX has multiple meaningful boundaries, and different backends want different
ones:

- execution-oriented tracing and replay want an early command/state boundary
- TeX-faithful rendering wants late layout or page structures
- semantic/reflow export wants a derived export structure

So the engine should use multiple layers rather than force every backend to
consume one early command IR.

## Why TeX Is Harder Than A Normal Parser

In TeX, scanning and parsing are stateful runtime behavior, not a clean
front-end pass.

Catcode assignments mean:

- tokenization depends on mutable state
- argument scanning depends on mutable state
- earlier commands can change the meaning of later source text
- token lists may be re-read under different contexts

So an early TeX command IR is not really an AST in the ordinary compiler sense.
It is closer to an execution trace over mutable scanner, expansion, and layout
state.

That makes the early layers useful for debugging, tracing, and replay, but a
poor universal shipout boundary.

## Effects, Not Just Commands

TeX commands are best understood by the kinds of effects they have, not by
forcing each command into one exclusive category.

The most important effect classes are:

- expansion effects
- parser/scanner state effects
- layout effects

Layout effects are the ones that matter directly for typesetting:

- create or append nodes
- begin or end lists
- create boxes
- create math lists
- pack or finalize lists and boxes
- emit specials, marks, inserts, and similar layout-relevant side effects

Expansion and parser state are still crucial, but mainly because they determine
when and how those layout effects happen.

## Layer Model

The proposed split is:

1. execution layer
2. layout layer
3. page layer
4. export layer

These are conceptual layers, not necessarily four isolated Python modules.

### 1. Execution Layer

This layer owns the stateful TeX machinery around scanning, expansion, and
command semantics:

- scanner state such as catcodes
- macro definitions, `\let`, and other bindings
- expansion control
- conditionals and branching
- command dispatch

It drives layout construction by issuing layout operations and consulting
layout-state queries such as current mode or last node when command semantics
need them.

This layer can have its own AST and IR, but that IR should be understood as
execution-oriented, not as the one true backend boundary.

Its best uses are:

- tracing
- replay
- serialization
- debugging

### 2. Layout Layer

The layout layer is also stateful during construction.

It owns the builder state that the executor interacts with, such as:

- current mode
- current list stack
- last node
- paragraph and box-building auxiliaries

For that reason, the layout layer should be split conceptually into two parts.

#### Layout Builder IR

This is the operational side of layout:

- begin a list
- append a node
- append glue, kern, penalty, rule, or whatsit
- begin or end math construction
- close and pack a box
- finish a paragraph

This is still a stateful instruction stream, not just a static object graph.

#### Layout Object IR

This is the structural result produced by the builder:

- nodes
- lists
- boxes
- math lists
- whatsits and related objects

This is the right boundary for TeX-faithful consumers that want the constructed
layout artifact rather than the full execution trace.

## 3. Page Layer

The page layer represents final shipped pages after the output routine has run.

This matters because important TeX behavior becomes page-local only at this
stage:

- `\box255`
- inserts and footnote placement
- marks as used by the output routine
- page headers and footers
- final shipout order

Backends that want faithful page output should consume this layer rather than
try to reconstruct page semantics from earlier execution history.

## 4. Export Layer

The export layer is a derived semantic structure for outputs that do not want
to be bound directly to page geometry.

Examples include:

- reflow HTML
- MathML
- later semantic or accessibility exports

This layer should be derived from layout and page structures, potentially with
source provenance attached, rather than from raw command IR alone.

## Specials As A Parallel Channel

`\special` commands, especially the `dvipdfm` family, should stay as a parallel
typed side channel shared by later backends.

They should not force the whole backend architecture to target early command IR.

So the model is:

- execution IR for TeX command behavior
- layout/page structures for faithful rendering
- typed special IR for driver-oriented side effects
- export IR for semantic output

## Backend Guidance

The intended backend boundaries are:

- DVI: consume late layout or page structures and emit raw specials as needed
- direct PDF: consume late layout or page structures plus typed specials
- faithful HTML: consume final shipped pages
- reflow HTML: consume export IR, or derive it from layout/page structures with
  provenance

The important rule is that each backend should target the latest layer that
matches its needs.

## Refactoring Implication

The current "parser" is better understood as an execution engine with embedded
scanning and layout construction.

The near-term refactor direction is therefore not "invent one universal IR", but
rather:

- keep execution concerns in the execution layer
- extract a narrower typed interface for layout construction
- preserve a structural layout object layer for faithful consumers
- formalize a page IR for shipout-oriented backends
- derive export IR separately for semantic outputs

This lets us reduce parser convolution without pretending TeX has a clean,
front-loaded parse stage.

## Short Version

- yes, multiple IR layers are useful
- no, every backend should not target one early command IR
- the execution layer is stateful and TeX-specific
- the layout layer has both a stateful builder side and a structural object side
- faithful backends should consume late layout/page structures
- semantic backends should consume a derived export IR
