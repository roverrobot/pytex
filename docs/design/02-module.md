# Module Framework

This note describes the module framework used by the current code base.

It belongs early in the design series, after the layer-separation note and
before the token-flow note. The reason is that the module system is not itself a
runtime layer like input flow, parser state, or layout building. Instead, it is
the composition mechanism that assembles those layers into a concrete `Parser`
instance.

In the current code, the central pieces are:

- `pytex/module.py`, which defines `Module` and the global `ModuleManager`
- `pytex/parser.py`, which imports the essential modules and populates the parser from the registered modules
- the `python -m pytex` entry point in `pytex/__main__.py`, which activates optional modules by importing them before creating `Parser`
- the individual feature files, which register themselves by constructing a `Module(...)` object at import time

Modules are used broadly. They are not limited to parser commands. The same
framework is used for parser-state pieces, token and assignment helpers,
resolver support, typeset services, font backends, and output backends.

## Main Idea

A module is a declarative bundle of parser contributions.

A module can contribute some combination of:

- commands
- state domains such as arrays or tables
- parameters stored in those domains
- parser attributes and helper methods
- an initialization hook that performs arbitrary parser setup

The parser does not hard-code all of these features one by one. Instead, it
creates a small core object and then asks every registered module to populate
it.

So the current design is:

- `Parser` is the live execution kernel
- modules are the composition mechanism that install capabilities onto that kernel

That is why this note fits naturally between the broad architectural layer note
and the later notes on token flow, parser state, and other subsystems.

## Registration Model

The registration mechanism is simple.

`module.py` defines a process-global registry:

- `ModuleManager = {}`

Each `Module` instance stores itself in that registry under its name when it is
constructed.

So registration is driven by import side effects. When a file does something
like:

```python
mod = Module("state", commands={...})
```

that module becomes visible to later parser instances.

This is important for understanding `parser.py`. The import list near the top of
`parser.py` does two jobs at once:

- it makes names available to the file in the ordinary Python sense
- it imports the module-defining files so that they register themselves with `ModuleManager`

As a result, parser construction is effectively a two-stage process:

1. import the feature files so they register their modules
2. construct `Parser`, which iterates over `ModuleManager` and applies those modules

## How `Parser` Uses Modules

In `Parser.__init__`, the parser first creates its built-in core state. For
example, it initializes grouped state domains, the input stack, the if-stack,
and other parser-owned runtime fields.

After that, it runs:

```python
for name, mod in ModuleManager.items():
    mod.populate(self)
```

So every module that is present in `ModuleManager` at that moment is applied to
that parser instance.

This gives the current framework a few important properties.

First, module application happens per parser instance. Even though the registry
is global, population is done on the fresh parser object.

Second, the set of active modules is determined before parser construction. If a
package such as `pytex.pdftex` or `pytex.texlive` is imported before `Parser()`
is called, its module entries will be present and will populate the parser. If
it is not imported, those features will not be installed.

Third, module order follows import order. Since `ModuleManager` is populated as
modules are imported, later modules are applied later. This matters when two
modules install the same parser attribute or otherwise override earlier setup.

## What A Module Can Install

The `Module` class currently accepts five contribution categories:

- `commands`
- `domains`
- `parameters`
- `attributes`
- `init`

The `populate()` order is:

1. `init`
2. commands
3. domains
4. attributes
5. parameters

That order is part of the current framework. It means a module can do some
initial setup first, then install commands and domains, then attach helper
methods or data, and finally seed parameter values and their accessors.

### Commands

A command contribution is a mapping from command name without the leading
backslash to a command object.

When populated, the module framework:

- prefixes the name with `\`
- fills in `command.name` if it was empty
- stores the command in `parser.equitable`
- also stores it in `parser.builtin`

So commands are installed both into the main control-sequence meaning table and
into a separate builtin dictionary.

Examples of command-oriented modules include `state`, `define`, `token`,
`conditional`, `expandable`, `file`, and many others.

### Domains

A domain contribution describes a parser-owned state table or array.

Each entry currently provides:

- a `generator`, which constructs the domain object for a specific parser
- an `accessor`, which may generate the command used to access that domain

When populated, the framework:

- constructs the domain with the current parser
- installs it as `parser.<name>`
- records it in `parser.arrays`
- optionally synthesizes and installs a control-sequence accessor command

This is how arrays such as `count`, `dimen`, `skip`, `muskip`, `toks`,
`catcode`, `mathcode`, `delcode`, `sfcode`, `lccode`, `uccode`, `box`, and
font-related tables are attached to the parser.

The framework also has one special-case naming rule here:

- the accessor for the `box` domain is installed as `\setbox`
- other domain accessors are installed as `\<name>`

So domains are not just stored data. They participate directly in command
syntax through their accessors.

### Parameters

A parameter contribution seeds one named item inside an existing domain.

Each parameter entry currently provides:

- a target `domain`
- a default `value`
- an `accessor` generator, if the parameter should be addressable as a control sequence

When populated, the framework:

- looks up the target domain on the parser
- computes the value, calling it first if the supplied value is callable
- stores the value either directly in globals or through a domain entry
- for non-global, non-tracing parameters, also stores the entry object on the parser as `parser.<name>`
- optionally installs an accessor command in `parser.equitable`

This is how things like `\tolerance`, `\globaldefs`, `\endlinechar`,
`\hsize`, `\vsize`, and many other parameters become available.

The distinction between global and grouped domains matters here.

- if the parameter belongs to `parser.globals`, the raw value is written directly
- otherwise an entry object is created in the target domain and initialized with `setGlobal(...)`

So parameter installation is already aligned with the grouped-state model used by
the rest of the parser.

### Attributes

An attribute contribution attaches ordinary Python attributes or methods to the
parser.

This is used for helper readers and service objects such as:

- `readInteger`
- `readDimen`
- `readGlue`
- `readFileName`
- `loadFontBackend`
- `resolver`
- tracing helpers
- various list and token readers

If the value is a callable but not a class, the module framework binds it as a
method using `types.MethodType`. Otherwise, it is attached directly as a plain
attribute.

So attributes are the escape hatch that lets the framework install parser-local
services that are not naturally expressed as TeX commands or grouped state.

### `init`

The `init(parser)` hook is the most open-ended part of the framework.

It runs before the other contribution categories and can perform arbitrary setup
on the parser.

This is currently used for things such as:

- creating runtime helper objects such as the typesetter bundle
- initializing page-building scratch structures
- initializing the hyphenator
- selecting a shipout backend such as DVI or PDF
- initializing tracing or timing-related runtime state

In practice, this is the mechanism used when a subsystem needs more than static
commands or tables.

## Essential Modules And Optional Modules

The current code has two practical classes of modules.

### Essential modules

These are imported directly by `parser.py` itself. They provide the core parser
capabilities and are present whenever `Parser` is imported.

That set includes modules such as:

- grouped state and accessors
- integer, dimension, glue, and token registers
- macro definition and expansion
- conditionals
- file I/O commands
- list building and mode handling
- paragraph and alignment support
- page building
- tracing
- typesetting support
- the default resolver module

So by the time `Parser` is constructed, these core modules are already
registered.

### Optional modules

These are activated by importing extra packages before constructing the parser.

Examples include:

- `pytex.texlive`, which replaces the default resolver attribute with a TeX Live based resolver
- `pytex.etex`, which adds e-TeX commands and state
- `pytex.pdftex`, which adds pdfTeX-related commands
- `pytex.opentype`, which adds OpenType and font-backend support
- `pytex.dvi` and `pytex.pdf`, which install shipout backends through module `init` hooks
- `pytex.html_reflow`, which installs the HTML reflow backend through its module initialization hook

So the framework supports a simple extension pattern: import the optional
feature package, then build `Parser()`.

## `python -m pytex` As The Main Usage Pattern

`pytex/__main__.py` shows the current module framework in its actual operating
style.

The sequence is roughly:

1. import `Parser` from `pytex.parser`
2. import optional feature packages such as `pytex.texlive`, `pytex.etex`, `pytex.pdftex`, and `pytex.opentype`
3. depending on the output mode, optionally import `pytex.dvi`, `pytex.pdf`, or `pytex.html_reflow`
4. construct `Parser(project_dir=...)`
5. optionally make a backend-specific adjustment, such as giving the SVG backend its output prefix
6. set runtime details such as the format name, dumper, profiling options, and tracing
7. parse the document

This illustrates two important facts about the module system.

First, parser configuration is import-driven rather than passed as a formal list
of modules to the constructor.

Second, the parser still allows post-construction adjustment. Modules populate
most of the runtime surface, but entry points can still override specific
attributes afterward when needed.

The resolver path is a good example.

- `parser.py` imports the default resolver module, which installs a `FileResolver()`
- `pytex/__main__.py` imports `pytex.texlive` before `Parser()`
- the `texlive` module installs a different `resolver` attribute
- because that module is registered later, its attribute wins during population
- after population, `Parser.__init__` clones the resolver if it is a `FileResolver` or subclass, so the parser instance gets a project-dir-specific resolver object

The backend path is similar.

- importing `pytex.dvi` or `pytex.pdf` registers a module whose `init` hook sets `parser.shipout`
- those modules therefore select the backend during parser construction
- importing `pytex.html_reflow` registers its initialization hook before `Parser()` is constructed

So modules do most of the assembly work, but not every configuration choice is
forced through the module API.

## Relation To The Layered Design

The module framework is not itself one of the runtime layers from the
layer-separation note.

Instead, it cuts across those layers.

For example:

- the input layer depends on modules that install token readers, token helpers, file readers, and source-related services
- parser-state support is installed through modules such as `state`, `integer`, `dimen`, `glue`, `toks`, and related accessor modules
- execution commands are installed through modules such as `define`, `conditional`, `expandable`, `file`, and `misc`
- layout and page-building services are installed through modules such as `lists`, `hmode`, `vmode`, `mmode`, `align`, `paragraph`, `page`, and `typeset`
- resolver, font, and backend support are also installed as modules

So modules are the assembly mechanism that binds the layers together into one
working parser.

This is why this document belongs near the front of the design sequence. Before
we discuss token flow or parser state in detail, it helps to state how those
subsystems arrive on the parser in the first place.

## Limits Of The Current Framework

The current module system is intentionally simple.

A few properties are worth stating explicitly.

- registration is global and import-driven
- there is no explicit per-parser module selection API
- module ordering follows import order
- later modules can override earlier attributes or commands
- the framework mixes declarative installation with arbitrary `init` hooks

That simplicity fits the current code well. It keeps the entry model light and
lets the engine grow by importing additional feature packages. At the same time,
it means that module interactions are controlled by import order rather than a
more formal dependency or capability system.
