# Pipe Backends

This note defines the current design for TeX-style pipe input commands such as:

```tex
\openin\foo="|extractbb -B cropbox -O figure.pdf"
```

The goal is to support the small set of pipe commands that real TeX workflows
need, without turning `\openin` into a general shell escape facility.

## Scope

Pipe commands are treated as a specialized input mechanism for `\openin`.

They are intentionally:

- read-only
- text-producing
- allowlisted by command name
- resolved inside pytex, not passed to the shell

This is a deliberate departure from engines that allow arbitrary process
execution behind `|command ...`. In pytex, a pipe command is a structured
request handled by a registered backend.

## High-Level Flow

The current execution path is:

```text
\openin
  -> OpenInOp.readValue
  -> resolver.openIn(name, "source")
  -> resolver.openPipeIn(name)              if name starts with "|"
  -> pytex.pipes.openPipe(...)
  -> registered handler
  -> text content
  -> PipeTextFile(StringIO)
  -> \read / \readline
```

So pipe commands sit at the resolver layer, not at the scanner or parser layer.

That is important because `\read` should not care whether its source is:

- a normal file
- an in-memory file
- an allowlisted pipe backend

All three are exposed as file-like input streams.

## Why Resolver-Owned

The resolver is already the abstraction that answers:

- what kind of file name is this?
- where should it be opened from?
- is it a real file, an in-memory file, or something virtual?

Pipe commands fit naturally here because they are another kind of readable
input source.

Putting them lower in the parser would be awkward:

- `\openin` would need special-case parser logic
- `\read` would need to know about process-like inputs
- file policy would be split across layers

Keeping the feature in the resolver means:

- the parser still just opens a readable stream
- `\read` and `\readline` stay unchanged
- access policy is centralized

## Security Model

Pytex does **not** support arbitrary external command execution through pipe
syntax.

Instead:

- the resolver checks whether the file name starts with `|`
- the pipe dispatcher parses the command name and arguments
- only registered command names are accepted
- the handler is a Python function inside `pytex.pipes.*`

So:

- `|extractbb -B cropbox -O figure.pdf` is allowed if `extractbb` is registered
- `|python something.py`
- `|sh -c ...`
- `|any-random-program`

are not supported

This keeps the feature deterministic, auditable, and portable.

## Registry Design

The process-wide registry lives in:

- [pytex/pipes/__init__.py](/Users/jma/dev/pytex/pytex/pipes/__init__.py)

The public surface is intentionally small:

- `registerPipeCommand(name, handler)`
- `unregisterPipeCommand(name)`
- `parsePipeCommand(spec)`
- `openPipe(resolver, spec)`

The registry is process-wide because pipe backends are effectively executable
capabilities, not parser-local values. Once a backend module is imported, the
capability is available to all parsers in that process.

## Lazy Backend Loading

Pipe backends are loaded lazily by command name.

The dispatcher does:

1. parse `|extractbb ...`
2. check whether `extractbb` is already registered
3. if not, try to import `pytex.pipes.extractbb`
4. re-check the registry

This gives a nice balance:

- no eager import of every possible pipe backend
- no special registration ceremony in parser startup
- backend modules remain self-contained

The mapping from command name to module is conservative:

- command names must match `[A-Za-z0-9_-]+`
- dashes are mapped to underscores for module import

So a command like `foo-bar` looks for `pytex.pipes.foo_bar`.

## Handler Contract

A pipe handler has the shape:

```python
def handler(resolver, args) -> str | None:
    ...
```

Where:

- `resolver` is the active per-parser resolver instance
- `args` is the parsed argument list after the command name
- the return value is:
  - a text string on success
  - `None` on failure

The handler does **not** return tokens or scanners.

That is deliberate. The pipe layer should describe an input stream, not parser
execution.

## Output Representation

Pipe handlers return plain text, and the resolver wraps it in:

- [PipeTextFile](/Users/jma/dev/pytex/pytex/resolver.py)

`PipeTextFile` is a small `StringIO` subclass with a `.name`.

This means the rest of the file-reading path can treat a pipe source like any
other text file:

- `\read` can consume it line by line
- `\readline` can consume it as raw text
- diagnostics still have a meaningful file-like name

The design intentionally stops at the stream boundary. Pipe results are not
turned into scanners directly.

## Resolver Integration

The current hook lives in:

- [FileResolver.openPipeIn](/Users/jma/dev/pytex/pytex/resolver.py)
- [FileResolver.openIn](/Users/jma/dev/pytex/pytex/resolver.py)

The rule is:

- if the requested name starts with `|`
- try the pipe registry first
- if a pipe handler returns content, wrap it as `PipeTextFile`
- if the name starts with `|` but no handler exists, return `None`

So pipe syntax is intercepted before ordinary file extension/type resolution.

That is the right precedence, because a literal file path beginning with `|`
is not a meaningful TeX use case here.

## First Backend: `extractbb`

The first concrete backend is:

- [pytex/pipes/extractbb.py](/Users/jma/dev/pytex/pytex/pipes/extractbb.py)

It exists to support the `dvipdfm(x)` graphics workflow used by LaTeX packages.

In that workflow, the driver may open:

```tex
|extractbb -B cropbox -O figure.pdf
```

and then read xbb-style metadata from the command output.

The pytex backend implements this internally by:

- parsing the recognized `extractbb` arguments
- opening the target PDF through resolver-aware file access
- reading page boxes with `pypdf`
- returning xbb-style text

That keeps the visible behavior close to TeX workflows without invoking an
external program.

## Why Handler Receives the Resolver

Passing the active resolver into the handler is important.

It lets a backend participate in the same file model as the parser:

- project directory restrictions
- in-memory files
- resolver-specific source lookup

For example, `extractbb` can inspect:

- resolver-managed in-memory files
- project-relative source paths

instead of assuming raw filesystem access.

That keeps pipe backends consistent with the rest of pytex’s file semantics.

## Error Model

Handlers signal failure by returning `None`.

That mirrors ordinary file resolution:

- missing file -> `openIn(...)` returns `None`
- missing/unsupported pipe command -> `openIn(...)` returns `None`
- failed pipe backend resolution -> `openIn(...)` returns `None`

So `\openin` and `\ifeof` continue to interact with pipe-backed streams the same
way they do with ordinary missing files.

This keeps the semantics simple and TeX-like.

## Non-Goals

The current design intentionally does **not** support:

- arbitrary shell execution
- writable pipes
- binary pipe streams
- long-running subprocess management
- parser-side token-producing handlers

Those would all move the feature away from “safe, structured input backends”
and toward general process execution, which is explicitly out of scope.

## Extension Path

New pipe backends should follow the same pattern:

1. create `pytex.pipes.<name>`
2. parse only the supported arguments for that command
3. use the provided resolver for file access
4. return text content
5. register the handler with `registerPipeCommand(...)`

This is meant for a small number of well-understood TeX-adjacent tools, not a
general plugin shell.

## Summary

The current pipe backend design is:

- resolver-owned
- allowlisted
- lazily registered by command name
- text-stream based
- integrated with resolver file semantics
- intentionally not a shell-escape mechanism

That gives pytex enough power to emulate important TeX workflows like
`extractbb`, while keeping the model safe, explicit, and portable.
