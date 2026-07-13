# Third-party notices

Pytex is distributed under the GNU General Public License, version 3. This
notice records the provenance of the generated format data distributed in
`pytex/data/formats/`.

## Bundled format data

The six `.pfmt` files are compressed Pytex serializations of initialized Plain
TeX, ePlain, and LaTeX states. They were regenerated with TeX Live 2023 from
`/usr/local/texlive/2023/texmf-dist` using Pytex 0.2.1 and these commands:

```console
python -m pytex --texlive /usr/local/texlive --engine xetex plain
python -m pytex --texlive /usr/local/texlive --engine xetex eplain.ini
python -m pytex --texlive /usr/local/texlive --engine xetex latex.ltx
python -m pytex --texlive /usr/local/texlive --engine pdftex plain
python -m pytex --texlive /usr/local/texlive --engine pdftex eplain.ini
python -m pytex --texlive /usr/local/texlive --engine pdftex latex.ltx
```

The primary initializer inputs are `tex/plain/base/plain.tex`,
`tex/eplain/eplain.ini`, and `tex/latex/base/latex.ltx`. Initializing them
also loads TeX Live's associated Plain/ePlain/LaTeX support files and
hyphenation data. The `.pfmt` files therefore remain subject to the license
and attribution terms of those upstream TeX Live components.

TeX Live's copying conditions and component-level licensing information are
available at <https://www.tug.org/texlive/copying.html>. In particular, some
Knuth-originated files have naming conditions for modified versions. Pytex
does not modify or redistribute these source files as standalone files; it
distributes only generated format state. When regenerating a bundled format
from another TeX Live release or adding a new format, update this notice with
the release, initializer, and relevant upstream license information.
