# Contributing to Pytex

## Development setup

Pytex requires Python 3.9 or newer and a TeX Live installation. Install the
checkout together with the test dependencies:

```console
python -m pip install -e ".[test]"
```

Use `--texlive DIRECTORY` when TeX Live is installed outside Pytex's platform
default location.

## Validation

Run the complete suite before proposing a change:

```console
python -m pytest -q
```

The suite exercises bundled format loading, the command-line interface, and
all output backends. When changing format serialization or its bundled data,
regenerate all six standard formats and update
`THIRD_PARTY_NOTICES.md` with the TeX Live release and provenance details.
