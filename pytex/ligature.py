"""
Shared ligature-program helpers.

This module factors out the low-level ligature/kern program walk used by the
TFM font backend and math Rule 14. Horizontal lists call the font backend's
shape interface and do not interpret ligature programs directly.
"""


def ligature_step(base, nxt):
    """
    Return the lig/kern step for (base, nxt), or None.

    Nodes are expected to be CharNode-like objects with:
    - .font
    - .char
    - .char_info.program
    """
    if base is None or nxt is None:
        return None
    if not hasattr(base, "char_info") or not hasattr(nxt, "char_info"):
        return None
    if not hasattr(base, "font") or not hasattr(nxt, "font"):
        return None
    if base.font != nxt.font:
        return None
    program = base.char_info.program
    if program is None:
        return None
    return program.get(ord(nxt.char))


def run_ligature_program(
    working,
    make_ligature,
    make_kern,
    source_nodes,
    make_insert=None,
):
    """
    Run a TeX ligature/kern program on a temporary working list.

    @param working:
        list of CharNode-like nodes; this list is modified in place and returned.
    @param make_ligature:
        callback(insert_char, replaced, step, base, nxt) -> new node
    @param make_kern:
        callback(step, base, nxt) -> kern-like node
    @param source_nodes:
        callback(node) -> list of source nodes represented by node
    @param make_insert:
        optional callback(insert_char, step, base, nxt) for the TeX opcode that
        retains both input glyphs and inserts a third glyph between them
    """
    cursor = 0
    while cursor < len(working) - 1:
        base = working[cursor]
        nxt = working[cursor + 1]
        step = ligature_step(base, nxt)
        if step is None:
            break
        if step.isKern:
            working.insert(cursor + 1, make_kern(step, base, nxt))
            cursor += 2
            continue
        insert_char = base.font[chr(step.insert)]
        if step.delete_current:
            replaced = source_nodes(base)
            if not step.keep_next:
                replaced.extend(source_nodes(nxt))
                working[cursor:cursor + 2] = [make_ligature(insert_char, replaced, step, base, nxt)]
            else:
                working[cursor] = make_ligature(insert_char, replaced, step, base, nxt)
        elif not step.keep_next:
            replaced = source_nodes(nxt)
            working[cursor + 1] = make_ligature(insert_char, replaced, step, base, nxt)
        else:
            inserted = (
                insert_char
                if make_insert is None
                else make_insert(insert_char, step, base, nxt)
            )
            working.insert(cursor + 1, inserted)
        cursor += step.move
    return working
