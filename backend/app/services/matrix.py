"""Building a Harris matrix from a spreadsheet.

Almost every excavation already has its stratigraphy in a spreadsheet, because
it was written on a context sheet in the trench and typed up in the evening.
Re-entering four hundred relationships by hand into a web form is not a
migration path, it is a reason not to migrate.

So: upload the sheet, match the contexts by their number, and write the
matrix. Three things make this trustworthy rather than merely fast.

**Nothing is written until it has all been checked.** The upload is planned
first and applied second, and the plan reports every row it could not match —
a context number that does not exist, a relationship word it does not
recognise — with the row number, so the sheet can be corrected rather than
guessed at.

**Impossible sequences are refused.** A Harris matrix is a directed acyclic
graph: if 1001 is above 1002 and 1002 is above 1003, then 1003 cannot be above
1001. A spreadsheet with that in it describes no stratigraphy that could
exist, and it is usually a transposed pair of columns rather than a
discovery. Importing it silently would turn a typing mistake into a published
sequence, so the cycle is found, reported with the loop spelled out, and the
import refuses until it is fixed.

**Both directions are written.** The schema stores A-above-B and B-below-A as
a pair, so a query never needs a UNION. A row that wrote only one direction
would produce a matrix that reads correctly from one context and is missing an
edge from the other.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.context import ContextRelationship, ExcavationContext
from app.models.enums import INVERSE_RELATION, StratigraphicRelation

#: What people actually type in the relationship column. The enum's own values
#: are accepted too; these are the words that appear on real context sheets and
#: would otherwise each cost somebody a failed import and a support question.
_WORDS: dict[str, StratigraphicRelation] = {
    "above": StratigraphicRelation.ABOVE,
    "over": StratigraphicRelation.ABOVE,
    "later than": StratigraphicRelation.ABOVE,
    "overlies": StratigraphicRelation.ABOVE,
    "below": StratigraphicRelation.BELOW,
    "under": StratigraphicRelation.BELOW,
    "earlier than": StratigraphicRelation.BELOW,
    "underlies": StratigraphicRelation.BELOW,
    "cuts": StratigraphicRelation.CUTS,
    "cut": StratigraphicRelation.CUTS,
    "truncates": StratigraphicRelation.CUTS,
    "cut by": StratigraphicRelation.CUT_BY,
    "is cut by": StratigraphicRelation.CUT_BY,
    "truncated by": StratigraphicRelation.CUT_BY,
    "fills": StratigraphicRelation.FILLS,
    "fill of": StratigraphicRelation.FILLS,
    "filled by": StratigraphicRelation.FILLED_BY,
    "filled with": StratigraphicRelation.FILLED_BY,
    "contemporary with": StratigraphicRelation.CONTEMPORARY_WITH,
    "contemporary": StratigraphicRelation.CONTEMPORARY_WITH,
    "same time as": StratigraphicRelation.CONTEMPORARY_WITH,
    "same as": StratigraphicRelation.SAME_AS,
    "equals": StratigraphicRelation.SAME_AS,
    "abuts": StratigraphicRelation.ABUTS,
    "butts": StratigraphicRelation.ABUTS,
    "bonded with": StratigraphicRelation.BONDED_WITH,
    "bonded": StratigraphicRelation.BONDED_WITH,
}

#: Relations that put one context earlier or later than another. Only these can
#: form an impossible loop — "contemporary with" and "same as" say two contexts
#: sit at the same point in the sequence, so a cycle among them is a statement,
#: not a contradiction.
_ORDERING = {
    StratigraphicRelation.ABOVE,
    StratigraphicRelation.CUTS,
    StratigraphicRelation.FILLS,
}

#: Column headings that mean each field. Matched case-insensitively after
#: stripping punctuation, so "Context no." and "context_number" both land.
_HEADINGS: dict[str, tuple[str, ...]] = {
    "context": ("context", "contextnumber", "contextno", "from", "unit", "su", "cataloguenumber"),
    "relation": ("relation", "relationship", "relates", "type", "stratigraphicrelation"),
    "related": (
        "related",
        "relatedcontext",
        "relatedcontextnumber",
        "to",
        "othercontext",
        "target",
        "relatedunit",
    ),
    "certainty": ("certainty", "confidence", "sure"),
    "notes": ("notes", "note", "comment", "comments"),
}


def _key(value: str) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def match_columns(columns: list[str]) -> dict[str, str | None]:
    """Work out which column is which, from the headings.

    Returns a mapping of field to column name, with ``None`` where nothing
    matched — the caller reports that rather than guessing, because a matrix
    built from the wrong column is worse than no matrix.
    """
    found: dict[str, str | None] = dict.fromkeys(_HEADINGS)
    used: set[str] = set()

    for field_name, candidates in _HEADINGS.items():
        for column in columns:
            if column in used:
                continue
            if _key(column) in candidates:
                found[field_name] = column
                used.add(column)
                break
    return found


def read_relation(value: object) -> StratigraphicRelation | None:
    """Turn what somebody typed into a relationship, or nothing."""
    if value is None:
        return None
    text = str(value).strip().lower().replace("_", " ")
    text = " ".join(text.split())
    if not text:
        return None
    if text in _WORDS:
        return _WORDS[text]
    for member in StratigraphicRelation:
        if member.value.replace("_", " ") == text:
            return member
    return None


@dataclass(slots=True)
class Edge:
    """One relationship the sheet is asking for."""

    row: int
    context_number: str
    related_number: str
    relation: StratigraphicRelation
    certainty: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class Problem:
    """A row that cannot be used, and why — in words, with its row number."""

    row: int
    message: str


@dataclass(slots=True)
class Plan:
    """What an import would do, worked out before anything is written."""

    edges: list[Edge] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    #: Loops in the sequence. Each is the chain of context numbers, closed —
    #: ``["1001", "1002", "1003", "1001"]`` — because a reader needs to see
    #: which link is wrong, not merely that something is.
    contradictions: list[list[str]] = field(default_factory=list)
    #: Rows already in the database. Re-importing a corrected sheet is normal,
    #: and re-adding what is already there is not an error.
    already_there: int = 0
    columns: dict[str, str | None] = field(default_factory=dict)

    @property
    def can_apply(self) -> bool:
        """A contradiction stops everything; unusable rows do not.

        The distinction matters. Twenty rows naming a context that does not
        exist yet is a sheet somebody can still get value from — import the
        other three hundred and fix those twenty. A cycle is different: it
        makes the *whole* sequence wrong, and there is no partial version of it
        worth having.
        """
        return not self.contradictions and bool(self.edges)


def plan(
    session: Session,
    site_id: uuid.UUID,
    rows: list[dict[str, object]],
    columns: dict[str, str | None],
) -> Plan:
    """Work out what a sheet would do, without writing anything."""
    result = Plan(columns=columns)

    if not columns.get("context") or not columns.get("related") or not columns.get("relation"):
        missing = [name for name in ("context", "relation", "related") if not columns.get(name)]
        result.problems.append(
            Problem(
                0,
                "The sheet needs a column for each of: the context, the "
                f"relationship, and the related context. Could not find: "
                f"{', '.join(missing)}.",
            )
        )
        return result

    contexts = session.scalars(
        select(ExcavationContext).where(ExcavationContext.site_id == site_id)
    ).all()
    by_number = {str(row.context_number).strip(): row for row in contexts}

    seen: set[tuple[str, str, StratigraphicRelation]] = set()

    for offset, row in enumerate(rows, start=2):  # row 1 is the heading
        left = str(row.get(columns["context"]) or "").strip()
        right = str(row.get(columns["related"]) or "").strip()
        word = row.get(columns["relation"])

        if not left and not right and not word:
            continue  # a blank line in the middle of a sheet is not an error

        if not left or not right:
            result.problems.append(Problem(offset, "The context or the related context is blank."))
            continue

        relation = read_relation(word)
        if relation is None:
            result.problems.append(
                Problem(offset, f"{word!r} is not a relationship this understands.")
            )
            continue

        if left == right:
            result.problems.append(
                Problem(offset, f"Context {left} is related to itself, which cannot be.")
            )
            continue

        for number in (left, right):
            if number not in by_number:
                result.problems.append(
                    Problem(offset, f"There is no context {number!r} on this site.")
                )
                break
        else:
            key = (left, right, relation)
            if key in seen:
                continue
            seen.add(key)
            result.edges.append(
                Edge(
                    row=offset,
                    context_number=left,
                    related_number=right,
                    relation=relation,
                    certainty=(
                        str(row.get(columns["certainty"])).strip()
                        if columns.get("certainty") and row.get(columns["certainty"])
                        else None
                    ),
                    notes=(
                        str(row.get(columns["notes"])).strip()
                        if columns.get("notes") and row.get(columns["notes"])
                        else None
                    ),
                )
            )

    _count_existing(session, result, by_number)
    result.contradictions = find_cycles(session, site_id, result.edges, by_number)
    return result


def _count_existing(
    session: Session, result: Plan, by_number: dict[str, ExcavationContext]
) -> None:
    """How many of these edges the database already holds."""
    for edge in result.edges:
        left = by_number[edge.context_number]
        right = by_number[edge.related_number]
        found = session.scalar(
            select(ContextRelationship).where(
                ContextRelationship.context_id == left.id,
                ContextRelationship.related_context_id == right.id,
                ContextRelationship.relation == edge.relation,
            )
        )
        if found is not None:
            result.already_there += 1


def find_cycles(
    session: Session,
    site_id: uuid.UUID,
    edges: list[Edge],
    by_number: dict[str, ExcavationContext],
) -> list[list[str]]:
    """Loops in the sequence, including edges already in the database.

    Checking the sheet alone would miss the common case: half the matrix is
    already imported, and the new rows close a loop with what is there. So the
    graph is built from both.

    Only ordering relations are followed — see :data:`_ORDERING`.
    """
    graph: dict[str, set[str]] = defaultdict(set)

    for edge in edges:
        if edge.relation in _ORDERING:
            graph[edge.context_number].add(edge.related_number)
        elif edge.relation in {
            StratigraphicRelation.BELOW,
            StratigraphicRelation.CUT_BY,
            StratigraphicRelation.FILLED_BY,
        }:
            # Stored as the inverse: B below A is the same statement as A above
            # B, and the cycle check has to see one direction consistently.
            graph[edge.related_number].add(edge.context_number)

    numbers = {row.id: str(row.context_number).strip() for row in by_number.values()}
    existing = session.scalars(
        select(ContextRelationship)
        .join(ExcavationContext, ExcavationContext.id == ContextRelationship.context_id)
        .where(ExcavationContext.site_id == site_id)
    ).all()
    for row in existing:
        if row.relation not in _ORDERING:
            continue
        left = numbers.get(row.context_id)
        right = numbers.get(row.related_context_id)
        if left and right:
            graph[left].add(right)

    found: list[list[str]] = []
    seen_cycles: set[tuple[str, ...]] = set()
    colour: dict[str, int] = {}  # 0 unvisited, 1 on the stack, 2 finished
    stack: list[str] = []

    def walk(node: str) -> None:
        colour[node] = 1
        stack.append(node)
        for nextn in sorted(graph.get(node, ())):
            state = colour.get(nextn, 0)
            if state == 1:
                loop = stack[stack.index(nextn) :] + [nextn]
                signature = tuple(sorted(loop))
                if signature not in seen_cycles:
                    seen_cycles.add(signature)
                    found.append(loop)
            elif state == 0:
                walk(nextn)
        stack.pop()
        colour[node] = 2

    for node in sorted(graph):
        if colour.get(node, 0) == 0:
            walk(node)
    return found


def apply(
    session: Session,
    site_id: uuid.UUID,
    result: Plan,
) -> int:
    """Write the planned edges, both directions each. Returns how many are new.

    The caller owns the transaction, and is expected to have checked
    :attr:`Plan.can_apply` first.
    """
    contexts = session.scalars(
        select(ExcavationContext).where(ExcavationContext.site_id == site_id)
    ).all()
    by_number = {str(row.context_number).strip(): row for row in contexts}

    written = 0
    for edge in result.edges:
        left = by_number.get(edge.context_number)
        right = by_number.get(edge.related_number)
        if left is None or right is None:  # pragma: no cover - planned away
            continue

        existing = session.scalar(
            select(ContextRelationship).where(
                ContextRelationship.context_id == left.id,
                ContextRelationship.related_context_id == right.id,
                ContextRelationship.relation == edge.relation,
            )
        )
        if existing is not None:
            continue

        session.add(
            ContextRelationship(
                context_id=left.id,
                related_context_id=right.id,
                relation=edge.relation,
                certainty=edge.certainty,
                notes=edge.notes,
            )
        )
        # The mirror. Without it the matrix reads correctly from one context
        # and is missing an edge from the other.
        inverse = INVERSE_RELATION[edge.relation]
        mirrored = session.scalar(
            select(ContextRelationship).where(
                ContextRelationship.context_id == right.id,
                ContextRelationship.related_context_id == left.id,
                ContextRelationship.relation == inverse,
            )
        )
        if mirrored is None:
            session.add(
                ContextRelationship(
                    context_id=right.id,
                    related_context_id=left.id,
                    relation=inverse,
                    certainty=edge.certainty,
                    notes=edge.notes,
                )
            )
        written += 1

    session.flush()
    return written
