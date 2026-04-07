# Pipe Backends

This note describes the current support for TeX-style pipe input names such as:

```tex
\openin\foo="|extractbb -B cropbox -O figure.pdf"
```

In pytex, pipe syntax is **not** a general shell-escape mechanism. It is a
small resolver-level extension that turns a restricted set of command names into
text streams.

The immediate motivation is compatibility with TeX workflows that expect a few
well-known pipe commands, especially `extractbb`, while keeping file access and
execution policy explicit.

## Scope

Pipe backends are currently:

- read-only
- text-producing
- allowlisted by command name
- implemented inside pytex
- opened through the resolver, not through the shell

This note only covers the current resolver-owned pipe mechanism. It does not
cover arbitrary subprocess execution, writable pipes, or a broader shell-escape
facility.

## Where Pipe Inputs Sit

Pipe syntax is handled by the resolver.

The relevant path is:

```text
source-opening command
  -> parser.resolver.openIn(name, "source")
  -> FileResolver.openPipeIn(name)          if name starts with "|"
  -> pytex.pipes.openPipe(...)
  -> registered handler
  -> text content
  -> PipeTextFile
```

That means pipe backends are not part of tokenization or parser-state logic.
They are just one more way to obtain a readable text stream.

This is why the same mechanism can be used by more than `\openin`. Any code
path that opens a **source** input through `resolver.openIn(..., "source")` can
benefit from it. In the current code, that includes at least:

- `\openin`
- `\input`
- any other source-opening helper that goes through the same resolver path

For `\openin`, the returned stream is later consumed by `\read` or
`\readline`. For `\input`, the returned stream is wrapped in a `Tokenizer` and
pushed onto `parser.input`.

## Why The Resolver Owns This

The resolver already decides:

- how file names are interpreted
- whether an input comes from the project directory, an in-memory file, or a
  resolver backend
- whether a requested name should open as text or binary

Pipe-backed source names fit naturally into that same abstraction. Keeping them
at the resolver layer has three practical benefits:

- `\openin`, `\input`, `\read`, and `\readline` do not need special parser-side
  knowledge of pipe commands
- file-access policy stays centralized
- ordinary file streams, in-memory files, and pipe streams all look like normal
  readable file-like objects to later code

## Security Model

Pytex does **not** pass `|command ...` to the operating-system shell.

Instead:

- the resolver checks whether the name starts with `|`
- the pipe dispatcher parses the command line with `shlex.split`
- only registered command names are accepted
- the implementation is a Python handler inside `pytex.pipes.*`

So a supported command such as:

```tex
|extractbb -B cropbox -O figure.pdf
```

can work, but arbitrary commands such as:

```tex
|python script.py
|sh -c ...
|anything-else
```

are not treated as shell commands.

This keeps the feature deterministic and auditable, and avoids turning source
input into a general process-execution channel.

## Pipe Command Registry

The registry lives in `pytex/pipes/__init__.py` and is process-wide.

The public operations are intentionally small:

- `registerPipeCommand(name, handler)`
- `unregisterPipeCommand(name)`
- `parsePipeCommand(spec)`
- `openPipe(resolver, spec)`

The registry is process-wide because imported pipe backends act like available
capabilities for the current Python process rather than parser-local state.
Once a backend module registers a command, later parsers in the same process can
use it too.

## Lazy Loading By Command Name

Pipe backends are loaded lazily.

When the resolver sees a name like:

```tex
|extractbb -B cropbox -O figure.pdf
```

it does the following:

1. parse the command name and arguments
2. check whether `extractbb` is already registered
3. if not, try to import `pytex.pipes.extractbb`
4. check the registry again

The import step is conservative:

- command names must match `[A-Za-z0-9_-]+`
- `-` in the command name is mapped to `_` in the Python module name

So `foo-bar` tries to load `pytex.pipes.foo_bar`.

This avoids eager imports while keeping backend modules self-registering.

## Handler Contract

A pipe handler has the shape:

```python
def handler(resolver, args) -> str | None:
    ...
```

The arguments are:

- `resolver`: the active resolver instance for the current parser
- `args`: the parsed argument list after the command name

The return value is:

- a text string on success
- `None` on failure or unsupported input

Handlers do not return tokens, tokenizers, or parser operations. Their job is
only to produce text.

## Stream Representation

Successful handlers return text, and `FileResolver.openPipeIn(...)` wraps that
text in `PipeTextFile`, a small `StringIO` subclass that also carries a `.name`.

That means later code can treat the result like an ordinary text file:

- `\read` can read from it line by line
- `\readline` can read raw text lines from it
- `\input` can pass it to `Tokenizer`
- diagnostics can still report a meaningful source name

So the pipe layer stops at the stream boundary. It does not introduce a special
scanner type.

## Resolver Integration

`FileResolver.openIn(...)` checks for pipe syntax before normal file lookup.

The rule is:

- if the requested name starts with `|`, try `openPipeIn(...)` first
- if a handler returns text, wrap it as `PipeTextFile` and return it
- if the name starts with `|` but no handler succeeds, return `None`

So pipe syntax has precedence over normal file resolution for source inputs.
That is appropriate here, since pytex does not otherwise assign a meaningful
filesystem interpretation to file names beginning with `|`.

## Current Concrete Backend: `extractbb`

The first built-in backend is `pytex.pipes.extractbb`.

This exists for the `dvipdfm(x)` graphics workflow, where TeX packages may try
to open something like:

```tex
|extractbb -B cropbox -p 2 -O figure.pdf
```

and then read xbb-style metadata from the resulting text stream.

The current pytex implementation does this internally:

- parse the supported `extractbb` arguments
- open the target PDF from resolver-managed in-memory binary files, or from the
  project directory
- inspect the PDF with `pypdf`
- emit xbb-style text such as `%%BoundingBox` and `%%HiResBoundingBox`

This reproduces the useful TeX-side behavior without invoking an external
program.

## Why The Handler Gets The Resolver

Passing the active resolver into the handler keeps pipe backends aligned with
normal pytex file policy.

In the current `extractbb` backend, this is used to support:

- resolver-managed in-memory binary files
- project-directory source access with the same path restrictions as ordinary
  source reads

This is important because pipe backends should not quietly bypass the resolver’s
file model.

## Error Model

Pipe handlers report failure by returning `None`.

That matches the resolver’s ordinary input-open convention:

- missing file -> `openIn(...)` returns `None`
- unknown pipe command -> `openIn(...)` returns `None`
- pipe backend cannot produce content -> `openIn(...)` returns `None`

So callers such as `\openin` or `\input` continue to use the usual success or
failure path for opening source inputs.

## Non-Goals

The current design intentionally does **not** support:

- arbitrary shell execution
- writable pipes
- binary pipe streams
- long-running subprocess management
- parser-side token-producing handlers

All of those would push the feature away from a small structured input mechanism
and toward general process execution, which is explicitly outside the current
model.

## Extension Pattern

A new pipe backend should follow the same shape:

1. create `pytex.pipes.<name>`
2. implement a handler `(resolver, args) -> str | None`
3. register it with `registerPipeCommand(...)`
4. use the provided resolver for file access when needed
5. return plain text only

This is intended for a small number of well-understood TeX-adjacent tools, not
for arbitrary external command execution.

## Summary

The current pipe-backend design is:

- resolver-owned
- allowlisted
- lazily loaded by command name
- text-stream based
- usable through any source-opening path that goes through `resolver.openIn`
- integrated with ordinary resolver file policy
- intentionally not a shell-escape mechanism

That gives pytex enough support for workflows such as `extractbb` while keeping
the behavior explicit and controlled.
