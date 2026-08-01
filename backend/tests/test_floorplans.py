"""Floor plans.

The property under test throughout is that **a plan owns no inventory**. It
draws a rectangle and says which cabinet the rectangle is; what the cabinet
holds is asked of the store, every time. A plan that cached its own object list
would be a second copy of the truth and wrong within a week — so the tests
below move objects around and check the plan follows without being touched.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Module, ModuleLevel, User, UserRole
from tests.conftest import auth_headers, make_user


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def keeper(db: Session) -> User:
    return make_user(db, email="keeper9@example.org", username="keeper9", role=UserRole.RESEARCHER)


@pytest.fixture
def store(client: TestClient, keeper: User) -> dict:
    """A room with a cabinet in it — the smallest store a plan is useful for."""
    headers = auth_headers(client, "keeper9")

    def add(kind: str, name: str, code: str, parent: str | None = None) -> dict:
        response = client.post(
            "/api/v1/storage/locations",
            json={"kind": kind, "name": name, "code": code, "parent_id": parent},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        return response.json()

    room = add("room", "Gallery 2", "G2")
    cabinet = add("cabinet", "Case 7", "C7", room["id"])
    other = add("cabinet", "Case 8", "C8", room["id"])
    return {"room": room, "cabinet": cabinet, "other": other}


@pytest.fixture
def plan(client: TestClient, keeper: User, store: dict) -> dict:
    response = client.post(
        "/api/v1/floorplans",
        json={
            "location_id": store["room"]["id"],
            "name": "Gallery 2 — ground floor",
            "width_m": 12,
            "height_m": 8,
        },
        headers=auth_headers(client, "keeper9"),
    )
    assert response.status_code == 201, response.text
    return response.json()


def png(width: int = 400, height: int = 300) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (240, 235, 225)).save(buffer, format="PNG")
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------
class TestDrawing:
    def test_a_plan_belongs_to_a_place(
        self, client: TestClient, keeper: User, store: dict, plan: dict
    ) -> None:
        assert plan["location_id"] == store["room"]["id"]
        assert plan["location_name"] == "Gallery 2"
        assert plan["shape_count"] == 0

    def test_shapes_are_replaced_in_one_call(
        self, client: TestClient, keeper: User, store: dict, plan: dict
    ) -> None:
        """Drawing is a rapid sequence of edits; a request per drag would make
        the editor feel like a form."""
        response = client.put(
            f"/api/v1/floorplans/{plan['id']}/shapes",
            json={
                "shapes": [
                    {"kind": "wall", "points": [[0, 0], [1, 0], [1, 1], [0, 1]], "label": "Room"},
                    {
                        "kind": "rect",
                        "points": [[0.1, 0.1], [0.3, 0.4]],
                        "label": "Case 7",
                        "location_id": store["cabinet"]["id"],
                    },
                ]
            },
            headers=auth_headers(client, "keeper9"),
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["shape_count"] == 2
        assert [shape["kind"] for shape in body["shapes"]] == ["wall", "rect"]

    def test_coordinates_outside_the_plan_are_refused(
        self, client: TestClient, keeper: User, plan: dict
    ) -> None:
        """Fractions of the plan, not pixels. A client sending pixel positions
        would draw everything in the top-left corner and look broken."""
        response = client.put(
            f"/api/v1/floorplans/{plan['id']}/shapes",
            json={"shapes": [{"kind": "rect", "points": [[120, 80], [400, 300]]}]},
            headers=auth_headers(client, "keeper9"),
        )
        assert response.status_code == 422
        assert "between 0 and 1" in response.text

    def test_a_rectangle_needs_two_corners(
        self, client: TestClient, keeper: User, plan: dict
    ) -> None:
        response = client.put(
            f"/api/v1/floorplans/{plan['id']}/shapes",
            json={"shapes": [{"kind": "rect", "points": [[0.1, 0.1]]}]},
            headers=auth_headers(client, "keeper9"),
        )
        assert response.status_code == 422

    def test_a_shape_cannot_point_at_a_location_that_does_not_exist(
        self, client: TestClient, keeper: User, plan: dict
    ) -> None:
        """It would draw a cabinet nobody can open."""
        response = client.put(
            f"/api/v1/floorplans/{plan['id']}/shapes",
            json={
                "shapes": [
                    {
                        "kind": "rect",
                        "points": [[0.1, 0.1], [0.2, 0.2]],
                        "location_id": "00000000-0000-0000-0000-000000000000",
                    }
                ]
            },
            headers=auth_headers(client, "keeper9"),
        )
        assert response.status_code == 422
        assert "does not exist" in response.json()["detail"]


# --------------------------------------------------------------------------
# The link to the store — the whole point
# --------------------------------------------------------------------------
class TestTheLink:
    def _draw(self, client: TestClient, plan: dict, store: dict) -> None:
        client.put(
            f"/api/v1/floorplans/{plan['id']}/shapes",
            json={
                "shapes": [
                    {
                        "kind": "rect",
                        "points": [[0.1, 0.1], [0.3, 0.4]],
                        "label": "Case 7",
                        "location_id": store["cabinet"]["id"],
                    },
                    {
                        "kind": "rect",
                        "points": [[0.5, 0.1], [0.7, 0.4]],
                        "label": "Case 8",
                        "location_id": store["other"]["id"],
                    },
                ]
            },
            headers=auth_headers(client, "keeper9"),
        )

    def _artifact(self, client: TestClient, location_id: str | None = None) -> dict:
        """A find, filed in a location.

        Filing goes through the movement register rather than a field on
        create: putting something in a box is an event, and the register is
        what answers "where has this been" a year later.
        """
        headers = auth_headers(client, "keeper9")
        project = client.post(
            "/api/v1/projects",
            json={"name": "Plan Test", "code": "pt-1", "is_public": True},
            headers=headers,
        ).json()
        site = client.post(
            "/api/v1/sites",
            json={"project_id": project["id"], "name": "S", "code": "S", "is_public": True},
            headers=headers,
        ).json()
        artifact = client.post(
            "/api/v1/artifacts",
            json={
                "site_id": site["id"],
                "inventory_number": "PT-1",
                "name": "Sherd",
                "is_public": True,
            },
            headers=headers,
        ).json()

        if location_id:
            moved = client.post(
                f"/api/v1/storage/artifacts/{artifact['id']}/move",
                json={"to_location_id": location_id, "reason": "accession"},
                headers=headers,
            )
            assert moved.status_code == 201, moved.text
        return artifact

    def test_a_shape_reports_what_its_location_holds(
        self, client: TestClient, keeper: User, store: dict, plan: dict
    ) -> None:
        self._draw(client, plan, store)
        self._artifact(client, store["cabinet"]["id"])

        body = client.get(
            f"/api/v1/floorplans/{plan['id']}", headers=auth_headers(client, "keeper9")
        ).json()
        counts = {shape["label"]: shape["item_count"] for shape in body["shapes"]}

        assert counts == {"Case 7": 1, "Case 8": 0}

    def test_moving_an_object_updates_the_plan_without_touching_it(
        self, client: TestClient, keeper: User, store: dict, plan: dict
    ) -> None:
        """The plan keeps no inventory, so it cannot go stale."""
        self._draw(client, plan, store)
        artifact = self._artifact(client, store["cabinet"]["id"])

        client.post(
            f"/api/v1/storage/artifacts/{artifact['id']}/move",
            json={"to_location_id": store["other"]["id"], "reason": "reorganisation"},
            headers=auth_headers(client, "keeper9"),
        )

        body = client.get(
            f"/api/v1/floorplans/{plan['id']}", headers=auth_headers(client, "keeper9")
        ).json()
        counts = {shape["label"]: shape["item_count"] for shape in body["shapes"]}

        assert counts == {"Case 7": 0, "Case 8": 1}

    def test_a_plan_never_reveals_objects_the_reader_could_not_already_see(
        self, client: TestClient, db: Session, keeper: User, store: dict, plan: dict
    ) -> None:
        """Counting is not a way around record permissions."""
        self._draw(client, plan, store)
        headers = auth_headers(client, "keeper9")
        artifact = self._artifact(client, store["cabinet"]["id"])
        client.patch(
            f"/api/v1/artifacts/{artifact['id']}", json={"is_public": False}, headers=headers
        )

        make_user(
            db,
            email="visitor9@example.org",
            username="visitor9",
            modules={Module.MUSEUM: ModuleLevel.VIEWER},
            grant_defaults=False,
        )
        body = client.get(
            f"/api/v1/floorplans/{plan['id']}", headers=auth_headers(client, "visitor9")
        ).json()
        counts = {shape["label"]: shape["item_count"] for shape in body["shapes"]}

        assert counts == {"Case 7": 0, "Case 8": 0}

    def test_deleting_a_plan_leaves_the_store_alone(
        self, client: TestClient, keeper: User, store: dict, plan: dict
    ) -> None:
        self._draw(client, plan, store)
        headers = auth_headers(client, "keeper9")

        assert client.delete(f"/api/v1/floorplans/{plan['id']}", headers=headers).status_code == 200
        assert (
            client.get(
                f"/api/v1/storage/locations/{store['cabinet']['id']}", headers=headers
            ).status_code
            == 200
        )


# --------------------------------------------------------------------------
# Finding the plan that shows a thing
# --------------------------------------------------------------------------
class TestFindingAPlan:
    def test_the_room_plan_is_found_from_a_shelf_inside_it(
        self, client: TestClient, keeper: User, store: dict, plan: dict
    ) -> None:
        """An object is in a box on a shelf in a cabinet; it is the *room's*
        plan that has the cabinet drawn on it."""
        headers = auth_headers(client, "keeper9")
        shelf = client.post(
            "/api/v1/storage/locations",
            json={
                "kind": "shelf",
                "name": "Shelf 1",
                "code": "S1",
                "parent_id": store["cabinet"]["id"],
            },
            headers=headers,
        ).json()

        found = client.get(f"/api/v1/floorplans/for-location/{shelf['id']}", headers=headers)
        assert found.status_code == 200, found.text
        assert [item["id"] for item in found.json()] == [plan["id"]]


# --------------------------------------------------------------------------
# The background image
# --------------------------------------------------------------------------
class TestBackground:
    def test_an_uploaded_plan_records_its_size(
        self, client: TestClient, keeper: User, plan: dict
    ) -> None:
        response = client.put(
            f"/api/v1/floorplans/{plan['id']}/image",
            files={"file": ("gallery.png", png(800, 600), "image/png")},
            headers=auth_headers(client, "keeper9"),
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert (body["image_width"], body["image_height"]) == (800, 600)
        assert body["image_url"] == f"/api/v1/floorplans/{plan['id']}/image"

    def test_replacing_the_background_leaves_every_shape_where_it_was(
        self, client: TestClient, keeper: User, store: dict, plan: dict
    ) -> None:
        """The reason coordinates are fractions and not pixels."""
        headers = auth_headers(client, "keeper9")
        client.put(
            f"/api/v1/floorplans/{plan['id']}/image",
            files={"file": ("small.png", png(400, 300), "image/png")},
            headers=headers,
        )
        client.put(
            f"/api/v1/floorplans/{plan['id']}/shapes",
            json={"shapes": [{"kind": "rect", "points": [[0.25, 0.5], [0.75, 0.9]]}]},
            headers=headers,
        )

        client.put(
            f"/api/v1/floorplans/{plan['id']}/image",
            files={"file": ("large.png", png(2400, 1800), "image/png")},
            headers=headers,
        )

        body = client.get(f"/api/v1/floorplans/{plan['id']}", headers=headers).json()
        assert body["image_width"] == 2400
        assert body["shapes"][0]["points"] == [[0.25, 0.5], [0.75, 0.9]]

    def test_a_file_that_is_not_an_image_is_refused(
        self, client: TestClient, keeper: User, plan: dict
    ) -> None:
        response = client.put(
            f"/api/v1/floorplans/{plan['id']}/image",
            files={"file": ("plan.png", b"not an image at all", "image/png")},
            headers=auth_headers(client, "keeper9"),
        )
        assert response.status_code == 422


# --------------------------------------------------------------------------
# Permissions
# --------------------------------------------------------------------------
class TestPlanPermissions:
    def test_drawing_is_a_supervisors_job(
        self, client: TestClient, db: Session, keeper: User, store: dict, plan: dict
    ) -> None:
        """Moving a cabinet on the plan is a claim about the building."""
        make_user(
            db,
            email="helper9@example.org",
            username="helper9",
            role=UserRole.STUDENT,
        )
        response = client.put(
            f"/api/v1/floorplans/{plan['id']}/shapes",
            json={"shapes": [{"kind": "rect", "points": [[0.1, 0.1], [0.2, 0.2]]}]},
            headers=auth_headers(client, "helper9"),
        )
        assert response.status_code == 403

    def test_reading_a_plan_needs_a_module_that_stores_things(
        self, client: TestClient, db: Session, keeper: User, plan: dict
    ) -> None:
        make_user(
            db,
            email="comms9@example.org",
            username="comms9",
            modules={Module.SOCIAL_MEDIA: ModuleLevel.EDITOR},
            grant_defaults=False,
        )
        response = client.get(
            f"/api/v1/floorplans/{plan['id']}", headers=auth_headers(client, "comms9")
        )
        assert response.status_code == 403
