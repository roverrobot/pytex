# Materializing

## Definition

Materializing means replacing a lazy high-level node with the concrete nodes it should contribute to the surrounding list.

In this codebase, lazy nodes can expose:

- `materialize_box_nodes(parser)`

which returns replacement nodes for list-level expansion.

## Materializing vs Pretypesetting

- **Materializing** is list-level expansion:
  - "Give me the concrete nodes that should be spliced here."
- **Pretypesetting** is object-level packing:
  - "Compute and cache final packed box metrics/content for this object."

A materialization method may call `pretypeset` internally, but the caller intent is different.

## Why We Need Both

- Some commands operate on surrounding list structure (`\lastbox`, `\unvbox`, `\prevdepth`) and need concrete nodes in place.
- Other operations only need a single object's packed metrics.
- Keeping these separate avoids over-eager packing and behavior changes.

## Current Materialization Paths

- Vertical list expansion:
  - `pytex/vmode.py`: `VList._expandNode` checks `materialize_box_nodes` first.
  - `VList.resolvePrevDepth` can realize lazy contextual nodes before depth lookup.
- Box commands:
  - `pytex/box.py`: `_materializeTailForLastBox` for `\lastbox`
  - `pytex/box.py`: `_materializeBoxListNodes` in `UnBox.execute` for `\unhbox/\unvbox`

## Behavioral Rule

For unboxing and similar list operations, materialize only lazy wrappers when needed; do not force full pretypesetting of unrelated box content.  
This keeps TeX-like semantics (for example avoiding accidental repacking side effects).

