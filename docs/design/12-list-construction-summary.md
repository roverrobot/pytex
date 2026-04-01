# List Construction Summary

This note summarizes the current state of list construction in the codebase.
It is not a forward-looking redesign document. The goal is to record the
present split between parser-owned construction logic and local packing or
conversion helpers.

## Main Point

List construction is increasingly parser-centric.

The parser owns the live execution context and the active list-building state.
Where a construct still needs parser state, math style, font resolution,
alignment templates, or other contextual decisions, the work is being moved out
of node-local `typeset` methods and into parser-owned helpers.

At the same time, simple local realization helpers still remain local when they
only:

- convert units
- pack already-built material
- compute box measures
- or wrap already-determined content

So the current code does **not** use one uniform rule that every `typeset`
method must disappear. The split is based on what kind of work the method does.

## Current Boundary

The current boundary in the code is roughly this.

### Parser-owned construction or realization

These are the areas that are now better treated as parser operations or
parser-owned typesetter logic because they still depend on live parser context
and make semantic layout decisions.

- paragraph construction
- math symbol realization
- delimiter realization
- accent-nucleus realization
- vertical alignment realization

In practice this means logic is moving toward parser-owned helpers such as the
math and alignment typesetters rather than remaining on the node classes
indefinitely.

### Local helper realization

These can remain local because they are mainly mechanical helpers rather than
semantic constructors.

- `MuGlue` conversion from mu glue to ordinary glue
- `MuKern` conversion from mu kern to ordinary kern
- `HBox` packing
- `VBox` packing
- `VTop` packing

These methods are still part of typesetting, but they are closer to box
construction utilities than to parser-level semantic decisions.

## Horizontal And Vertical Lists

The live horizontal and vertical lists are still important runtime objects.
They are not just temporary data produced for a backend.

This matters because the parser and layout code still need honest access to the
current lists for TeX-like behavior, including state-sensitive operations and
introspection.

So the current direction is:

- keep the live lists real
- let the parser and its helpers build them
- avoid scattering major construction logic across unrelated node classes
- avoid collapsing structure earlier than necessary

## Math Construction

Math construction is one of the clearest places where parser-owned realization
is a better fit than node-local `typeset` methods.

The remaining math cases that were still too concrete at the node level are the
ones that need contextual decisions such as:

- choosing symbol form
- choosing delimiter size or extensible construction
- computing accent placement details
- interacting with current style or parser-owned math helpers

That work is now better centralized in `MathTypesetter` instead of being spread
across several node classes.

## Alignment Construction

`VAlignment` is also better treated as parser-owned construction.

Although the final result may still be ordinary boxes and glue, the alignment
step itself is not just box packing. It still depends on structured alignment
logic such as:

- collecting cell material
- working with templates
- handling spans
- computing column widths
- inserting tabskip-related structure

So `VAlignment` belongs with parser-owned alignment logic rather than with the
simple `VBox` and `HBox` packers.

## Packing Helpers Still Matter

Moving more construction logic into parser-owned helpers does not make the box
packers obsolete.

`HBox`, `VBox`, and `VTop` still have a clear role:

- package already-built lists
- compute dimensions
- provide the box objects that later stages expect

Similarly, mu-kern and mu-glue conversion helpers still make sense as local
operations because they convert one already-understood representation into
another.

## Relationship To The Design Notes

This summary is consistent with the surrounding design notes:

- the parser is becoming the execution kernel
- list-building is part of the parser-owned runtime machinery
- there is a distinction between execution, layout construction, and later
  output or export layers
- not every piece of realization belongs at the same layer

This note is intentionally narrower than those broader architecture notes. It is
only about where list-construction work currently lives and why.

## Short Version

The current code is moving toward this rule of thumb:

- if a method performs semantic or context-dependent list construction, it
  should move toward parser ops or parser-owned typesetters
- if a method only packs, measures, or converts already-decided material, it can
  remain local

That is the current state of the code and the rationale behind the recent moves
for math and alignment handling.
