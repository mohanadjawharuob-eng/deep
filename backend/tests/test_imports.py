"""The spreadsheet importer.

The property that matters most is the one in the middle: **nothing is written
until a person has approved what each column fills, and seen what every row
would do**. Several tests below exist only to hold that line — an importer that
quietly guesses is worse than no importer, because the mistakes it makes are
invisible and four thousand rows deep.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Module, ModuleLevel, User, UserRole
from app.services import importer, spreadsheets
from tests.conftest import auth_headers, make_user


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def registrar(db: Session) -> User:
    return make_user(
        db,
        email="registrar@example.org",
        username="registrar",
        role=UserRole.VISITOR,
        modules={Module.MUSEUM: ModuleLevel.SUPERVISOR},
        grant_defaults=False,
    )


@pytest.fixture
def collection(client: TestClient, registrar: User) -> dict:
    response = client.post(
        "/api/v1/museum/collections",
        json={
            "name": "Ceramics",
            "code": "cer",
            "accession_pattern": "{prefix}.{year}.{seq:04d}",
            "accession_prefix": "NM",
        },
        headers=auth_headers(client, "registrar"),
    )
    assert response.status_code == 201, response.text
    return response.json()


def workbook(rows: list[list], *, headers: list[str], sheet: str = "Objects") -> bytes:
    """A real .xlsx, built the way a curator's file would be."""
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    worksheet = book.active
    worksheet.title = sheet
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def upload(client: TestClient, data: bytes, *, filename="catalogue.xlsx", **form) -> dict:
    response = client.post(
        "/api/v1/imports",
        files={"file": (filename, data)},
        data={"record_type": "museum_object", **form},
        headers=auth_headers(client, "registrar"),
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------
# Reading files
# --------------------------------------------------------------------------
class TestReading:
    def test_an_xlsx_is_read_with_its_headings(self) -> None:
        data = workbook(
            [["NM.2024.0001", "Cooking pot", 210]], headers=["Acc. No.", "Title", "Height"]
        )
        sheet = spreadsheets.read(data, filename="c.xlsx")

        assert sheet.columns == ["Acc. No.", "Title", "Height"]
        assert sheet.rows[0]["Title"] == "Cooking pot"

    def test_a_csv_finds_its_own_delimiter(self) -> None:
        data = b"Acc. No.;Title;Height\r\nNM.1;Bowl;90\r\n"
        sheet = spreadsheets.read(data, filename="c.csv")

        assert sheet.columns == ["Acc. No.", "Title", "Height"]
        assert sheet.rows[0]["Title"] == "Bowl"

    def test_excels_utf8_bom_does_not_end_up_in_the_first_heading(self) -> None:
        """Excel writes a byte-order mark, and a naive read makes the first
        column ``﻿Acc. No.`` — which then matches no synonym at all."""
        data = "Acc. No.,Title\nNM.1,Bowl\n".encode("utf-8-sig")
        sheet = spreadsheets.read(data, filename="c.csv")

        assert sheet.columns[0] == "Acc. No."

    def test_two_columns_with_the_same_heading_stay_separate(self) -> None:
        data = workbook([["a", "b"]], headers=["Notes", "Notes"])
        sheet = spreadsheets.read(data, filename="c.xlsx")

        assert sheet.columns == ["Notes", "Notes (2)"]
        assert sheet.rows[0] == {"Notes": "a", "Notes (2)": "b"}

    def test_a_blank_heading_is_named_for_its_position(self) -> None:
        data = workbook([["x", "y"]], headers=["Title", None])
        sheet = spreadsheets.read(data, filename="c.xlsx")

        assert sheet.columns == ["Title", "Column 2"]

    def test_blank_separator_rows_are_not_records(self) -> None:
        data = workbook(
            [["NM.1", "Bowl"], [None, None], ["NM.2", "Jar"]], headers=["Acc. No.", "Title"]
        )
        sheet = spreadsheets.read(data, filename="c.xlsx")

        assert len(sheet.rows) == 2

    def test_the_heading_row_can_be_further_down(self) -> None:
        """Files routinely open with a title and a blank line."""
        data = workbook(
            [["Museum of Somewhere", None], ["Acc. No.", "Title"], ["NM.1", "Bowl"]],
            headers=["Catalogue export", None],
        )
        sheet = spreadsheets.read(data, filename="c.xlsx", header_row=3)

        assert sheet.columns[:2] == ["Acc. No.", "Title"]
        assert sheet.rows[0]["Title"] == "Bowl"

    def test_an_old_xls_is_refused_with_the_way_out(self) -> None:
        with pytest.raises(spreadsheets.SpreadsheetError, match="save it as .xlsx"):
            spreadsheets.read(b"\xd0\xcf\x11\xe0", filename="old.xls")

    def test_a_file_with_no_data_rows_says_so(self) -> None:
        data = workbook([], headers=["Acc. No.", "Title"])
        with pytest.raises(spreadsheets.SpreadsheetError, match="no data rows"):
            spreadsheets.read(data, filename="c.xlsx")


# --------------------------------------------------------------------------
# Guessing, and the limits of it
# --------------------------------------------------------------------------
class TestSuggestions:
    def test_common_headings_are_recognised(self) -> None:
        mapping = spreadsheets.suggest_mapping(
            "museum_object", ["Acc. No.", "Object Name", "Material", "Maker"]
        )

        assert mapping["Acc. No."] == "accession_number"
        assert mapping["Object Name"] == "title"
        assert mapping["Material"] == "materials"
        assert mapping["Maker"] == "maker"

    def test_a_heading_nothing_matches_is_left_unmapped(self) -> None:
        """The honest answer, and the safe one."""
        mapping = spreadsheets.suggest_mapping("museum_object", ["Shelf ref (old system)"])

        assert mapping["Shelf ref (old system)"] is None

    def test_two_columns_are_never_suggested_for_one_field(self) -> None:
        """Whichever came last would silently win."""
        mapping = spreadsheets.suggest_mapping("museum_object", ["Title", "Object Name"])

        assert mapping["Title"] == "title"
        assert mapping["Object Name"] is None

    def test_the_report_shows_what_a_column_holds(self) -> None:
        data = workbook(
            [["NM.1", "Bowl"], ["NM.2", None], ["NM.3", "Jar"]], headers=["Acc. No.", "Title"]
        )
        sheet = spreadsheets.read(data, filename="c.xlsx")
        reports = {r.column: r for r in spreadsheets.describe_columns("museum_object", sheet)}

        assert reports["Title"].samples == ["Bowl", "Jar"]
        assert reports["Title"].filled == 2
        assert reports["Title"].total == 3


# --------------------------------------------------------------------------
# What a cell means
# --------------------------------------------------------------------------
class TestCoercion:
    def spec(self, name: str, kind: str, **extra):
        from app.services.forms import FormField

        return FormField(name=name, label=name.title(), kind=kind, **extra)

    def test_a_measurement_keeps_its_number_and_drops_its_unit(self) -> None:
        assert importer.coerce(self.spec("height_mm", "number"), "210 mm", lookups={}) == 210.0
        assert importer.coerce(self.spec("height_mm", "number"), "c. 12,5", lookups={}) == 12.5

    def test_a_cell_with_two_numbers_is_refused(self) -> None:
        """``120 x 80`` is two measurements in one column, and picking one
        would silently discard the other."""
        with pytest.raises(importer.CellError, match="more than one"):
            importer.coerce(self.spec("height_mm", "number"), "120 x 80", lookups={})

    def test_an_ambiguous_date_is_refused_rather_than_guessed(self) -> None:
        with pytest.raises(importer.CellError, match="day/month or month/day"):
            importer.coerce(self.spec("acquisition_date", "date"), "03/04/2019", lookups={})

    def test_an_unambiguous_date_is_taken(self) -> None:
        assert (
            importer.coerce(self.spec("acquisition_date", "date"), "2019-04-03", lookups={})
            == "2019-04-03"
        )
        assert (
            importer.coerce(self.spec("acquisition_date", "date"), date(2019, 4, 3), lookups={})
            == "2019-04-03"
        )

    def test_bce_years_come_through_negative(self) -> None:
        assert importer.coerce(self.spec("date_from", "integer"), "1200 BCE", lookups={}) == -1200
        assert importer.coerce(self.spec("date_to", "integer"), "300 CE", lookups={}) == 300

    def test_the_blanks_a_spreadsheet_is_full_of_read_as_nothing(self) -> None:
        for blank in ("", "  ", "-", "n/a", "N/A", "unknown", "?"):
            assert importer.coerce(self.spec("title", "text"), blank, lookups={}) is None

    def test_a_list_in_one_cell_is_split(self) -> None:
        assert importer.coerce(self.spec("materials", "tags"), "bronze; iron", lookups={}) == [
            "bronze",
            "iron",
        ]
        assert importer.coerce(self.spec("materials", "tags"), "bone and antler", lookups={}) == [
            "bone",
            "antler",
        ]

    def test_a_value_list_is_matched_by_name_not_guessed(self) -> None:
        spec = self.spec("condition", "select", value_list="condition")
        lookups = {"condition": {"good": "good", "poor": "poor"}}

        assert importer.coerce(spec, " Good ", lookups=lookups) == "good"
        with pytest.raises(importer.CellError, match="not one of the values"):
            importer.coerce(spec, "goodish", lookups=lookups)

    def test_text_longer_than_the_field_is_reported_not_truncated(self) -> None:
        spec = self.spec("object_type", "text", max_length=10)
        with pytest.raises(importer.CellError, match="longer than"):
            importer.coerce(spec, "a" * 40, lookups={})


# --------------------------------------------------------------------------
# The whole flow
# --------------------------------------------------------------------------
class TestFlow:
    def test_uploading_reports_the_columns_and_writes_nothing(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        data = workbook(
            [["NM.2024.0001", "Cooking pot", "210"]],
            headers=["Acc. No.", "Title", "Height"],
        )
        batch = upload(client, data)

        assert batch["status"] == "analysed"
        assert batch["total_rows"] == 1
        columns = {c["column"]: c for c in batch["columns_detail"]}
        assert columns["Acc. No."]["suggested_field"] == "accession_number"
        assert columns["Title"]["field_label"] == "Object name"
        assert columns["Height"]["samples"] == ["210"]

        # Nothing has been catalogued.
        listing = client.get(
            "/api/v1/museum/objects", headers=auth_headers(client, "registrar")
        ).json()
        assert listing["total"] == 0

    def test_the_mapping_is_confirmed_before_anything_runs(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        data = workbook([["NM.1", "Bowl", "spare"]], headers=["Acc. No.", "Title", "Junk"])
        batch = upload(client, data)

        confirmed = client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={
                "mapping": {"Junk": None, "Title": "title"},
                "defaults": {"collection_id": collection["id"]},
            },
            headers=auth_headers(client, "registrar"),
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "mapped"
        assert confirmed.json()["mapping"]["Junk"] is None

    def test_a_field_cannot_be_filled_by_two_columns(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        """Whichever column came last would win, silently."""
        data = workbook([["a", "b"]], headers=["Title", "Object Name"])
        batch = upload(client, data)

        response = client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={"mapping": {"Title": "title", "Object Name": "title"}},
            headers=auth_headers(client, "registrar"),
        )
        assert response.status_code == 422
        assert "one column" in response.json()["detail"]

    def test_a_column_that_is_not_in_the_file_is_refused(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        data = workbook([["a"]], headers=["Title"])
        batch = upload(client, data)

        response = client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={"mapping": {"Titel": "title"}},
            headers=auth_headers(client, "registrar"),
        )
        assert response.status_code == 422
        assert "no column named" in response.json()["detail"]

    def test_preview_reports_every_row_and_still_writes_nothing(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        data = workbook(
            [
                ["NM.2024.0001", "Cooking pot", "210"],
                ["NM.2024.0002", "Bowl", "120 x 80"],
            ],
            headers=["Acc. No.", "Title", "Height"],
        )
        batch = upload(client, data)
        client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={
                "mapping": {"Height": "height_mm"},
                "defaults": {"collection_id": collection["id"]},
            },
            headers=auth_headers(client, "registrar"),
        )

        preview = client.post(
            f"/api/v1/imports/{batch['id']}/preview", headers=auth_headers(client, "registrar")
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["valid_rows"] == 1
        assert body["invalid_rows"] == 1

        # Failures first, and numbered as they are in Excel: heading is row 1,
        # so the second data row is row 3.
        assert body["rows"][0]["row_number"] == 3
        assert not body["rows"][0]["ok"]
        assert "more than one" in body["rows"][0]["errors"][0]

        listing = client.get(
            "/api/v1/museum/objects", headers=auth_headers(client, "registrar")
        ).json()
        assert listing["total"] == 0

    def test_commit_creates_the_good_rows_and_skips_the_bad(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        data = workbook(
            [
                ["NM.2024.0001", "Cooking pot", "210"],
                ["NM.2024.0002", "Bowl", "120 x 80"],
                ["NM.2024.0003", "Lamp", "60"],
            ],
            headers=["Acc. No.", "Title", "Height"],
        )
        batch = upload(client, data)
        client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={
                "mapping": {"Height": "height_mm"},
                "defaults": {"collection_id": collection["id"]},
            },
            headers=auth_headers(client, "registrar"),
        )

        committed = client.post(
            f"/api/v1/imports/{batch['id']}/commit", headers=auth_headers(client, "registrar")
        )
        assert committed.status_code == 200, committed.text
        assert committed.json()["valid_rows"] == 2

        listing = client.get(
            "/api/v1/museum/objects", headers=auth_headers(client, "registrar")
        ).json()
        assert listing["total"] == 2
        titles = {item["title"] for item in listing["items"]}
        assert titles == {"Cooking pot", "Lamp"}

    def test_all_or_nothing_refuses_the_whole_file(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        data = workbook(
            [["NM.1", "Pot", "210"], ["NM.2", "Bowl", "120 x 80"]],
            headers=["Acc. No.", "Title", "Height"],
        )
        batch = upload(client, data)
        client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={
                "mapping": {"Height": "height_mm"},
                "defaults": {"collection_id": collection["id"]},
            },
            headers=auth_headers(client, "registrar"),
        )

        response = client.post(
            f"/api/v1/imports/{batch['id']}/commit?all_or_nothing=true",
            headers=auth_headers(client, "registrar"),
        )
        assert response.status_code == 409
        assert "nothing was written" in response.json()["detail"]

        listing = client.get(
            "/api/v1/museum/objects", headers=auth_headers(client, "registrar")
        ).json()
        assert listing["total"] == 0

    def test_an_imported_number_is_numbered_by_the_collections_own_rule(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        """A number that does not fit the pattern is recorded and flagged,
        exactly as it would be if somebody had typed it into the form."""
        data = workbook(
            [["NM.2024.0001", "Fits"], ["1974.1a", "Does not fit"]],
            headers=["Acc. No.", "Title"],
        )
        batch = upload(client, data)
        client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={"defaults": {"collection_id": collection["id"]}},
            headers=auth_headers(client, "registrar"),
        )
        client.post(
            f"/api/v1/imports/{batch['id']}/commit", headers=auth_headers(client, "registrar")
        )

        listing = client.get(
            "/api/v1/museum/objects", headers=auth_headers(client, "registrar")
        ).json()
        flags = {item["accession_number"]: item["number_is_legacy"] for item in listing["items"]}
        assert flags == {"NM.2024.0001": False, "1974.1a": True}

    def test_a_committed_import_cannot_be_remapped(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        data = workbook([["NM.1", "Bowl"]], headers=["Acc. No.", "Title"])
        batch = upload(client, data)
        client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={"defaults": {"collection_id": collection["id"]}},
            headers=auth_headers(client, "registrar"),
        )
        client.post(
            f"/api/v1/imports/{batch['id']}/commit", headers=auth_headers(client, "registrar")
        )

        response = client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={"mapping": {"Title": "description"}},
            headers=auth_headers(client, "registrar"),
        )
        assert response.status_code == 409

    def test_an_import_can_be_undone(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        data = workbook([["NM.1", "Bowl"], ["NM.2", "Jar"]], headers=["Acc. No.", "Title"])
        batch = upload(client, data)
        client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={"defaults": {"collection_id": collection["id"]}},
            headers=auth_headers(client, "registrar"),
        )
        client.post(
            f"/api/v1/imports/{batch['id']}/commit", headers=auth_headers(client, "registrar")
        )

        reverted = client.delete(
            f"/api/v1/imports/{batch['id']}/records", headers=auth_headers(client, "registrar")
        )
        assert reverted.status_code == 200, reverted.text
        assert "2 records deleted" in reverted.json()["detail"]

        listing = client.get(
            "/api/v1/museum/objects", headers=auth_headers(client, "registrar")
        ).json()
        assert listing["total"] == 0

    def test_undoing_keeps_a_record_somebody_has_since_edited(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        """Somebody has worked on it. Undoing the import should not throw that away."""
        data = workbook([["NM.1", "Bowl"], ["NM.2", "Jar"]], headers=["Acc. No.", "Title"])
        batch = upload(client, data)
        client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={"defaults": {"collection_id": collection["id"]}},
            headers=auth_headers(client, "registrar"),
        )
        client.post(
            f"/api/v1/imports/{batch['id']}/commit", headers=auth_headers(client, "registrar")
        )

        listing = client.get(
            "/api/v1/museum/objects", headers=auth_headers(client, "registrar")
        ).json()
        edited = listing["items"][0]
        client.patch(
            f"/api/v1/museum/objects/{edited['id']}",
            json={"description": "Catalogued properly"},
            headers=auth_headers(client, "registrar"),
        )

        reverted = client.delete(
            f"/api/v1/imports/{batch['id']}/records", headers=auth_headers(client, "registrar")
        )
        assert "1 were kept" in reverted.json()["detail"]

        remaining = client.get(
            "/api/v1/museum/objects", headers=auth_headers(client, "registrar")
        ).json()
        assert remaining["total"] == 1
        assert remaining["items"][0]["id"] == edited["id"]


# --------------------------------------------------------------------------
# Permissions
# --------------------------------------------------------------------------
class TestImportPermissions:
    def test_importing_needs_supervisor_access_to_the_module_it_writes_into(
        self, client: TestClient, db: Session, registrar: User
    ) -> None:
        make_user(
            db,
            email="helper@example.org",
            username="helper",
            role=UserRole.VISITOR,
            modules={Module.MUSEUM: ModuleLevel.CONTRIBUTOR},
            grant_defaults=False,
        )
        response = client.post(
            "/api/v1/imports",
            files={"file": ("c.csv", b"Title\nBowl\n")},
            data={"record_type": "museum_object"},
            headers=auth_headers(client, "helper"),
        )
        assert response.status_code == 403

    def test_one_registrars_import_is_not_anothers(
        self, client: TestClient, db: Session, registrar: User, collection: dict
    ) -> None:
        batch = upload(client, workbook([["NM.1", "Bowl"]], headers=["Acc. No.", "Title"]))

        make_user(
            db,
            email="other@example.org",
            username="other",
            role=UserRole.VISITOR,
            modules={Module.MUSEUM: ModuleLevel.SUPERVISOR},
            grant_defaults=False,
        )
        response = client.get(
            f"/api/v1/imports/{batch['id']}", headers=auth_headers(client, "other")
        )
        assert response.status_code == 404


# --------------------------------------------------------------------------
# Values set once for the whole file
# --------------------------------------------------------------------------
class TestDefaults:
    """A value set for every row is checked exactly as a column is.

    Before, ``defaults`` bypassed coercion entirely and went to the database as
    whatever the client sent. That worked only because the one thing anybody
    set that way was already an identifier — the moment a shared date or count
    is set, the two routes into a record start disagreeing about what a value
    means, and the difference is invisible until something fails much later.
    """

    def test_a_shared_value_is_coerced_like_a_column(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        data = workbook([["NM.1", "Bowl"]], headers=["Acc. No.", "Title"])
        batch = upload(client, data)
        client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={
                "mapping": {"Acc. No.": "accession_number", "Title": "title"},
                # A count typed as text, exactly as a person would type it.
                "defaults": {"collection_id": collection["id"], "object_count": "3"},
            },
            headers=auth_headers(client, "registrar"),
        )

        preview = client.post(
            f"/api/v1/imports/{batch['id']}/preview", headers=auth_headers(client, "registrar")
        ).json()

        assert preview["rows"][0]["errors"] == []
        # An integer, not the string that was sent.
        assert preview["rows"][0]["values"]["object_count"] == 3

    def test_a_shared_value_may_be_a_name_rather_than_an_identifier(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        """The tray screen sets the collection from a dropdown; a person
        writing to the API by hand has only the name. Both resolve."""
        data = workbook([["NM.1", "Bowl"]], headers=["Acc. No.", "Title"])
        batch = upload(client, data)
        client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={
                "mapping": {"Acc. No.": "accession_number", "Title": "title"},
                "defaults": {"collection_id": "Ceramics"},
            },
            headers=auth_headers(client, "registrar"),
        )

        preview = client.post(
            f"/api/v1/imports/{batch['id']}/preview", headers=auth_headers(client, "registrar")
        ).json()

        assert preview["rows"][0]["errors"] == []
        assert preview["rows"][0]["values"]["collection_id"] == collection["id"]

    def test_an_impossible_shared_value_is_reported_and_writes_nothing(
        self, client: TestClient, registrar: User, collection: dict
    ) -> None:
        data = workbook([["NM.1", "Bowl"], ["NM.2", "Lamp"]], headers=["Acc. No.", "Title"])
        batch = upload(client, data)
        client.patch(
            f"/api/v1/imports/{batch['id']}",
            json={
                "mapping": {"Acc. No.": "accession_number", "Title": "title"},
                "defaults": {"collection_id": collection["id"], "object_count": "several"},
            },
            headers=auth_headers(client, "registrar"),
        )

        preview = client.post(
            f"/api/v1/imports/{batch['id']}/preview", headers=auth_headers(client, "registrar")
        ).json()

        # It is wrong for every row, and says so on every row, because a person
        # scanning the preview reads rows and not a header.
        assert preview["valid_rows"] == 0
        assert preview["invalid_rows"] == 2
        for row in preview["rows"]:
            assert any("set for every row" in problem for problem in row["errors"])

        listing = client.get(
            "/api/v1/museum/objects", headers=auth_headers(client, "registrar")
        ).json()
        assert listing["total"] == 0
