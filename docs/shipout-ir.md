# Shipout IR design

## Goal

Refactor shipout so that the base shipout class owns the traversal of TeX boxes,
while concrete backends implement a small rendering-oriented interface. The
initial target is the current DVI backend, but the split should also support a
future LaTeX-oriented PDF backend and a layout-faithful HTML backend.

This design deliberately stays close to the current engine rather than trying to
solve every future backend requirement up front.

## Current problem

`pytex.dvi.DVIShipout` currently mixes two responsibilities:

1. walking shipped `hlist` / `vlist` structures, including glue, kern, shifted
   boxes, and whatsits; and
2. encoding the resulting page into DVI bytecode.

That makes DVI the de facto definition of shipout, and makes it harder to reuse
page traversal logic for other backends.

## Proposed split

The base `Shipout` class becomes the shared page walker. It:

- packs the box if needed;
- owns the logical page position during shipout;
- traverses `hlist` / `vlist` recursively;
- resolves glue and kern movement;
- handles shifted child boxes;
- emits whatsits in list order.

Concrete backends implement a small IR-like method set:

- `begin_page(box)`
- `end_page(box)`
- `define_font(font)`
- `select_font(font)`
- `move_to(h, v)`
- `set_char(node)`
- `set_rule(node, parent_box, move)`
- `special(text)`

The design keeps these in a single backend namespace rather than splitting core
and extension operations into separate classes. That keeps the immediate DVI
refactor small and leaves room to grow later.

## Why these operations

### Page boundaries

Page boundaries need to be explicit because DVI, PDF, and HTML page emitters all
need page start/end hooks.

### Font definition and selection

The walker does not know how a backend chooses to identify fonts. DVI uses font
numbers and writes font definitions into the stream. Other backends may cache
font objects or CSS/font-face declarations differently. The walker only needs to
know that a font may need one-time definition plus per-use selection.

### `move_to`

The walker computes logical placement and reduces box traversal to positioned
output. A backend may encode that as absolute movement, relative movement, or a
higher-level drawing command.

### `set_char`

Characters and ligatures are the basic text emission primitive. The current
implementation keeps the DVI-oriented `set_char` name because the engine still
ships character nodes. If a future backend wants a glyph-oriented interface, the
method can be generalized later without changing the traversal split.

### `set_rule`

Rules are kept as a first-class primitive because they are not text and they are
common in TeX layout. The current signature intentionally preserves the existing
DVI-compatible rule semantics by passing the parent box and the DVI `move`
flag. This keeps the refactor low risk. If later backends want a normalized
rectangle API, that can be introduced once there is an actual need.

### `special`

`\special` must remain part of shipout. In DVI it is serialized as an opaque
string. In future PDF or HTML backends it may be interpreted to implement color,
XObject/image placement, links, graphics, or backend-specific extensions.

Keeping `special(text)` in the IR preserves this escape hatch while still moving
ordinary page traversal into the base walker.

## Non-goals for this step

This refactor does not try to standardize:

- PDF graphics state operations;
- an image or XObject API;
- link annotations;
- file operations as rendering IR.

Deferred file operations already travel through whatsits, and should continue to
behave as shipout-time side effects rather than core drawing primitives.

## Notes on future extension

If multiple future backends need to interpret the same families of specials, the
engine can later lift common constructs into first-class methods such as:

- `set_color(...)`
- `place_xobject(...)`
- `begin_link(...)` / `end_link(...)`

That should be done only when there is concrete duplication to remove.

## Patch scope

This patch performs only the structural split:

- move box traversal from `DVIShipout` into `typeset.shipout.Shipout`;
- keep `DVIShipout` as a concrete implementation of the backend IR;
- preserve current DVI behavior as closely as possible.
