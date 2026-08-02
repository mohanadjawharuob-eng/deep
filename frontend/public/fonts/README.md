# Fonts

Three faces, self-hosted so the platform works on a machine with no internet.

| Family         | Copyright                                    | Licence |
| -------------- | -------------------------------------------- | ------- |
| Source Sans 3  | Adobe, Reserved Font Name "Source"           | SIL Open Font Licence 1.1 |
| Source Serif 4 | Adobe, Reserved Font Name "Source"           | SIL Open Font Licence 1.1 |
| IBM Plex Mono  | IBM Corp.                                    | SIL Open Font Licence 1.1 |

All three are OFL 1.1, which permits redistribution as part of a larger work
including these files, provided the licence travels with them. The full text
is at <https://openfontlicense.org/>, and each project publishes its own copy:

- Source Sans 3 — <https://github.com/adobe-fonts/source-sans>
- Source Serif 4 — <https://github.com/adobe-fonts/source-serif>
- IBM Plex Mono — <https://github.com/IBM/plex>

The `.woff2` files here are Google Fonts' builds, fetched by
`scripts/fetch-fonts.sh`. That script also writes `fonts.css` and trims the
subsets down to latin, latin-ext and greek.

The files are committed rather than fetched at build time, because a build
that reaches the internet is a build that fails on a machine that cannot.
