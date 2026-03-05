# Lazy Typesetting

## Motivation

TeX-like parsing builds semantic list nodes first, but full box packing can be expensive and context-sensitive.  
Lazy typesetting delays final packing until a consumer actually needs concrete box material.

## Core Idea

- Parse/build phase may keep high-level nodes in lists.
- Pack/layout phase runs later, when needed.
- Packed results are cached (typically via `_typeset_cache`) so repeated access is stable and cheap.

## Why This Helps

- Avoids unnecessary work for nodes that may never be shipped out or measured.
- Keeps structure available longer for tooling and transformations.
- Matches TeX behavior where some values are only fixed when inspected (for example when querying `\badness` after a box pack operation).

## Main Mechanisms in This Codebase

- Box-level lazy packing:
  - `pytex/box.py`: `HBox.pretypeset`, `VBox.pretypeset`, `Box.typeset`
- Paragraph-level lazy realization:
  - `pytex/paragraph.py`: `Paragraph.pretypeset`, `Paragraph.materialize_box_nodes`
- Display-math lazy realization:
  - `pytex/mmode.py`: `DisplayMathList.pretypeset`, `DisplayMathList.materialize_box_nodes`
- Alignment lazy realization:
  - `pytex/align.py`: `Alignment.pretypeset`, `Alignment.materialize_box_nodes`

## Invariants

- Lazy nodes must preserve TeX-visible behavior once realized.
- Realization should preserve traceability (`source` links) from produced nodes to origin node.
- Cached packed results should be deterministic for the same captured context.
- Operations that need concrete dimensions (for example page building or `\prevdepth` inspection) are allowed to force realization.

