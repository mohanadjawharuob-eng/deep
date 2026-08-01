# Design brief — Archaeological Research & Heritage Management Platform

**Give this whole document to the designer.** It is written to be pasted in as-is.

Everything below describes software that already exists and runs. The designer's
job is not to invent the product; it is to decide how it should look and feel.
Where this document is specific, it is because the constraint is real — a
permission rule, a database field, a way archaeologists actually work — and not
because a preference has been guessed at.

---

## 1. What this is

A single web platform for an archaeological institute. It holds five permissioned
modules over one login and one database:

| Module | What it holds |
|---|---|
| **Archaeology** | Projects, sites, excavation units, contexts, stratigraphy, finds, samples, GIS layers, drone and photogrammetry data, site diaries, publications, 3D models |
| **Museum collection** | Accessioned objects, collections, conservation history, exhibitions, loans, storage, environmental monitoring, labels and QR codes |
| **Social media repository** | Posts per platform, campaigns, press releases, scheduled publication |
| **Management** | Budgets, grants, equipment, contracts, staff, tasks, calendar, travel, vehicles, reports |
| **Office & storage inventory** | Computers, GPS units, cameras, drones, total stations, tools, consumables, and an excavation kit builder |

Plus a sixth, later: a **digital archive**.

Today the Archaeology and Museum modules are built, along with the shared storage
hierarchy, search and map. The other three are planned and will arrive as further
sections of the same navigation — the design must anticipate them without
designing them.

## 2. Who uses it

Four kinds of person, and they want different things from the same screens.

**The field director.** Runs excavations. Lives in projects, sites, contexts and
the map. Works on a laptop in a site house with poor light and worse internet.
Wants speed and density; is annoyed by whitespace that costs a scroll.

**The cataloguer / registrar.** Enters museum objects, all day, for weeks. This
is the single most important user to design for, because the work is repetitive
and the interface is the whole job. They come from FileMaker and expect its
model: one record shown as a card of labelled fields in tabs, dropdowns driven by
value lists, related records in inline panels, and a **record counter** — "34 of
211" with ◀ ▶ — that walks the found set without going back to the list. That
model is already implemented; the design should make it *good*, not replace it.

**The student / volunteer.** Contributes records that a supervisor approves.
Needs to always know whether what they entered is live or pending, and never to
be surprised by a permission they do not have.

**The director / administrator.** Wants a dashboard that answers "what is
happening" in one glance, and reports that print.

## 3. The character we are after

Words the user gave: **"extremely good yet simple, but make it a good website."**

Read that as: a professional instrument, not a consumer app. Specifically —

- **Dense but calm.** A cataloguer needs fifty fields on one screen. That must not
  feel like a wall. Rhythm, grouping and typographic hierarchy do this work;
  whitespace alone cannot afford it.
- **Quiet chrome, loud content.** The record is the point. Navigation, toolbars
  and headers should recede.
- **Serious, not corporate.** This is an institution that handles objects three
  thousand years old. Earth over neon. Warmth over sterility. No gradients, no
  drop shadows for their own sake, no bounce.
- **Honest.** Where the platform is uncertain — an approximate coordinate, an
  unapproved record, an accession number that does not match the collection's
  pattern — the design must show it rather than smooth it over. See §7.

Reference points worth looking at, for tone rather than imitation: the British
Museum's collection online, Notion's density in tables, Linear's restraint in
chrome, and — for the record card specifically — FileMaker layouts.

## 4. What already exists, that you are designing over

There is a working interface. It is deliberately plain, so it can be replaced.

- **No UI library.** Hand-written CSS. Every colour, space, radius, font size and
  shadow is a CSS custom property in `frontend/src/styles/tokens.css`. Redefining
  those tokens restyles the entire application without touching a component.
- **Three stylesheets:** `tokens.css` (the design system), `base.css` (buttons,
  fields, tables, badges, cards), `app.css` (layout: shell, sidebar, record card,
  tree, map, results).
- **Light and dark**, both first-class. Dark is warm, not an inversion.
- **Components** live in `frontend/src/components/` and screens in
  `frontend/src/routes/`.

**What we want back from the designer:** a coherent visual system expressed as
tokens plus a set of screen designs. Not a rewrite of the code.

## 5. Screens to design

In priority order. The first four are worth real effort; the rest can follow the
system.

### 5.1 The museum record card — *the most important screen*

One object, shown as a FileMaker-style layout. What is on it today:

- **Header:** title, accession number (monospace), status / condition / review
  badges, a **record counter** (`‹ 34 / 211 ›`), and Edit / Save / Cancel.
- **Five tabs:** Identification · Measurement · Acquisition & provenance ·
  Condition & location · Links & publication.
- **Within a tab, groups** — a card per group with a heading and optional help
  text, containing fields laid out on a **twelve-column grid**. Each field
  declares its own width (4 of 12, 6 of 12, and so on), so the design must work
  for arbitrary combinations, not a fixed two-column form.
- **Field types to design, in both read and edit state:** text, long text,
  number with a unit suffix (mm, g), integer, date, boolean, single-select,
  multi-select, free-text tag list (materials, techniques), reference to another
  record (some as a dropdown, some as a search-and-pick), and raw JSON.
- **Portals** — inline panels of related records below the fields: conservation
  history, location history, photographs, exhibitions. Small dense tables.

Design questions we would like answered: How does read mode differ from edit
mode without the page jumping? How does a required-but-empty field read? How does
a fifty-field tab stay navigable? What does the record counter look like so it
reads as position, not pagination?

### 5.2 The catalogue list

A dense table of objects: accession number, title, collection, type, condition,
status. Filters above it (search box, collection, status, condition). Needs to
work at 20 rows and at 20,000. Row density, zebra or not, how a "legacy number"
flag reads, how the active filter set is shown.

### 5.3 The dashboard

Counts as large numbers linked to their lists; recent projects; an activity feed.
Should answer "what is happening" without scrolling.

### 5.4 The storage tree

A two-pane screen. Left: the hierarchy — Institution → Building → Floor → Room →
Cabinet → Shelf → Drawer → Box — expandable, searchable, up to eight levels deep.
Right: the selected location's details and everything filed inside it, finds and
museum objects together. The tree must stay legible at depth on a narrow pane.

### 5.5 Also needed

- **Sign in** — one card, e-mail/username and password.
- **The application shell** — sidebar grouped by module (only modules this user
  can reach are shown), top bar with search, theme toggle, user menu.
- **Search results** — mixed record types in one list, filter chips by type with
  counts.
- **The map** — full-bleed Leaflet with a floating filter and legend. Restricted
  sites are drawn as hollow dashed markers and must read as "approximately here".
- **Archaeology list and detail screens** — projects, sites, finds. Same patterns
  as the museum ones, less specialised.
- **Empty, loading and error states** for every one of the above. These are not
  an afterthought; a new institution's platform is *entirely* empty states for
  its first week.

## 6. Components the system needs

Buttons (primary, default, ghost, danger; three sizes) · text input, textarea,
select, checkbox, switch, date field, number field with unit · search box · tag
input with removable chips · lookup field with a results menu · badge (neutral,
success, warning, danger, info, accent) · card with header and body · dense table
· tabs · tree row · breadcrumb · pager · record counter · inline alert (info,
warning, danger) · skeleton loader · spinner · empty state · modal · toast ·
avatar · dropdown menu · timeline (for movement history) · map marker set.

## 7. Rules the design must not break

These are not stylistic. Each one exists because breaking it causes harm.

1. **An approximate coordinate must never look like a surveyed one.** Site
   locations are blurred for records at risk of looting. A map that draws both
   identically silently undoes that protection.
2. **A pending record must be visibly pending.** A student's unapproved entry
   must never be mistakable for an approved one.
3. **Navigation shows only what the user can reach.** A menu item leading to
   "403 Forbidden" teaches people to distrust the interface.
4. **Accession numbers are identity.** Show them in monospace, never truncate
   them, never re-order their characters for display. A number that does not
   match its collection's pattern is flagged, not hidden.
5. **Destructive actions need a confirmation that names the thing.** "Delete
   IOA.2024.0001 — Everted-rim cooking pot?", not "Are you sure?".
6. **Nothing is saved until Save is pressed**, and the interface says how many
   fields are pending.
7. **Every screen must work at 1280×800**, which is what the laptops in the field
   house are. Tablet matters for the store (someone is standing at a shelf).
   Phone is nice to have.
8. **Accessibility is not optional:** 4.5:1 contrast for text in both themes,
   visible focus rings, full keyboard operation, and never colour as the only
   carrier of meaning.

## 8. Practical constraints

- **Fonts** must be self-hostable and free. A humanist sans for the interface, a
  monospace for numbers and codes, optionally a serif for long descriptive text.
- **No icon font.** Inline SVG, one consistent set, 1.5px stroke.
- **Diacritics matter.** Site and personal names carry them. Arabic and Hebrew
  appear in transliteration; right-to-left is not required now, but do not choose
  a font that cannot render the Latin diacritics.
- **Numbers must be tabular** in tables and in accession numbers.
- **Print**: reports and object labels are printed. A print stylesheet is in scope.

## 9. What to deliver

1. **Design tokens** — the full palette (light and dark), type scale, spacing
   scale, radii, borders, shadows, transitions. Delivered as a table of names and
   values, or directly as CSS custom properties matching
   `frontend/src/styles/tokens.css`.
2. **A component sheet** — every component in §6, in every state (default, hover,
   focus, active, disabled, error, loading), in both themes.
3. **The screens in §5**, at 1280 wide, both themes, with realistic content — real
   accession numbers, real site names, a fifty-field form actually full.
4. **Empty, loading and error variants** of the four priority screens.
5. **A short rationale** — one page on why the palette and type choices suit an
   institution that handles antiquities.

Please avoid: stock photography, illustration-heavy empty states, colour used
decoratively, and any component whose behaviour is not in §6.

---

## Appendix — what happens after the design arrives

*(For the project owner, not the designer. This is the plan for turning a
delivered design into the running product.)*

**Step 1 — Review the tokens before anything else.** The palette and type scale
decide how everything looks. Check them against §7: 4.5:1 contrast in both
themes, and no meaning carried by colour alone. Getting this wrong is cheap to
fix now and expensive later.

**Step 2 — Apply the tokens.** Replace the values in
`frontend/src/styles/tokens.css`. Because no component hard-codes a colour or a
size, the whole application changes at once. This is a small, fast change, and
the first moment you see the design on real data.

**Step 3 — Look at every screen with the new tokens, before rebuilding
anything.** Most of the difference between "plain" and "designed" is in the
tokens. What is still wrong after this step is genuinely structural, and that
list is much shorter than it looks beforehand.

**Step 4 — Rebuild components, one at a time.** Buttons, fields, cards, tables,
badges — each is a block in `base.css`. Change one, look at every screen, move
on. Doing them one at a time means a mistake is always attributable.

**Step 5 — Rebuild layouts.** `app.css` holds the shell, the record card, the
tree and the map. These change shape, not just colour, so they come after the
components they contain are settled.

**Step 6 — Re-check the eight rules in §7.** Specifically: is an approximate
marker still obviously approximate; is a pending record still obviously pending;
does the sidebar still hide modules the user cannot reach.

**Step 7 — Check the states nobody designs for.** Empty database. Slow network.
A failed request. A 300-character object title. A collection with 20,000 objects.
A user with access to exactly one module.

**Step 8 — Print.** Object labels and reports go on paper.

Two things worth deciding before commissioning the work:

- **Ask for tokens, not a picture.** A design delivered only as images has to be
  measured and guessed at. A design delivered as named values applies in an hour.
- **The layout logic is not up for redesign.** The record card is generated from
  the backend's form layout. A design that requires hand-placing individual
  fields would throw away the property that makes the museum module maintainable
  — that adding a field to the catalogue is a one-line backend change.
