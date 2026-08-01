"""The storage hierarchy and the movement register.

Two properties carry most of the weight here:

- **The materialised path must never lie.** It is denormalised, so a rename or
  a reparent that forgets to rebuild the subtree leaves cabinets claiming to be
  in rooms they left. Several tests below exist only to catch that.
- **The register is append-only and frozen at the time of the move.** Renaming
  a room later must not rewrite what the register said on the day.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    Artifact,
    Module,
    ModuleLevel,
    MovementReason,
    ResourceType,
    StorageKind,
    StorageLocation,
    User,
    UserRole,
)
from app.services import storage_locations as tree
from tests.conftest import auth_headers, make_user


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def keeper(db: Session) -> User:
    """Somebody who may reshape the store."""
    return make_user(db, email="keeper@example.org", username="keeper", role=UserRole.RESEARCHER)


def add_location(
    client: TestClient,
    *,
    kind: str,
    name: str,
    code: str,
    parent_id: str | None = None,
    identifier: str = "keeper",
    **fields: object,
):
    return client.post(
        "/api/v1/storage/locations",
        json={"kind": kind, "name": name, "code": code, "parent_id": parent_id, **fields},
        headers=auth_headers(client, identifier),
    )


@pytest.fixture
def store(client: TestClient, keeper: User) -> dict:
    """A small but realistic store: institution → building → room → cabinet → shelf."""
    institution = add_location(client, kind="institution", name="National Museum", code="NM").json()
    building = add_location(
        client, kind="building", name="Building A", code="A", parent_id=institution["id"]
    ).json()
    room = add_location(
        client, kind="room", name="Room 203", code="203", parent_id=building["id"]
    ).json()
    cabinet = add_location(
        client, kind="cabinet", name="Cabinet 4", code="CAB-4", parent_id=room["id"]
    ).json()
    shelf = add_location(
        client, kind="shelf", name="Shelf B", code="B", parent_id=cabinet["id"]
    ).json()
    return {
        "institution": institution,
        "building": building,
        "room": room,
        "cabinet": cabinet,
        "shelf": shelf,
    }


@pytest.fixture
def artifact(client: TestClient, keeper: User) -> dict:
    project = client.post(
        "/api/v1/projects",
        json={"name": "Storage Test", "code": "st-1", "is_public": True},
        headers=auth_headers(client, "keeper"),
    ).json()
    site = client.post(
        "/api/v1/sites",
        json={"project_id": project["id"], "name": "Test Site", "code": "TS", "is_public": True},
        headers=auth_headers(client, "keeper"),
    ).json()
    response = client.post(
        "/api/v1/artifacts",
        json={
            "site_id": site["id"],
            "inventory_number": "ST-2024-001",
            "name": "Bronze fibula",
            "is_public": True,
        },
        headers=auth_headers(client, "keeper"),
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------
# Building the hierarchy
# --------------------------------------------------------------------------
class TestHierarchy:
    def test_a_location_records_its_route_from_the_root(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        shelf = store["shelf"]

        assert shelf["path"] == "/nm/a/203/cab-4/b"
        assert (
            shelf["display_path"] == "National Museum → Building A → Room 203 → Cabinet 4 → Shelf B"
        )
        assert shelf["depth"] == 4

    def test_the_breadcrumb_reads_from_the_root_down(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        detail = client.get(
            f"/api/v1/storage/locations/{store['shelf']['id']}",
            headers=auth_headers(client, "keeper"),
        ).json()

        assert [row["name"] for row in detail["ancestors"]] == [
            "National Museum",
            "Building A",
            "Room 203",
            "Cabinet 4",
        ]

    def test_levels_may_be_skipped(self, client: TestClient, keeper: User, store: dict) -> None:
        """A crate on a room floor has no cabinet, and that is not an error."""
        response = add_location(
            client, kind="box", name="Crate 7", code="C7", parent_id=store["room"]["id"]
        )
        assert response.status_code == 201, response.text
        assert response.json()["path"] == "/nm/a/203/c7"

    def test_the_hierarchy_cannot_be_inverted(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        response = add_location(
            client, kind="room", name="Impossible", code="X", parent_id=store["shelf"]["id"]
        )
        assert response.status_code == 422
        assert "cannot sit inside" in response.json()["detail"]

    def test_two_children_of_one_parent_cannot_share_a_code(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        first = add_location(
            client, kind="shelf", name="Shelf C", code="C", parent_id=store["cabinet"]["id"]
        )
        assert first.status_code == 201

        duplicate = add_location(
            client, kind="shelf", name="Another C", code="C", parent_id=store["cabinet"]["id"]
        )
        assert duplicate.status_code == 409

    def test_the_same_code_is_fine_in_a_different_parent(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        other_room = add_location(
            client, kind="room", name="Room 204", code="204", parent_id=store["building"]["id"]
        ).json()
        other_cabinet = add_location(
            client, kind="cabinet", name="Cabinet 4", code="CAB-4", parent_id=other_room["id"]
        )
        # Every store in the world has a Cabinet 4 in more than one room.
        assert other_cabinet.status_code == 201

    def test_the_tree_endpoint_nests_the_whole_store(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        roots = client.get("/api/v1/storage/tree", headers=auth_headers(client, "keeper")).json()

        assert len(roots) == 1
        institution = roots[0]
        assert institution["name"] == "National Museum"
        building = institution["children"][0]
        room = building["children"][0]
        cabinet = room["children"][0]
        assert cabinet["children"][0]["name"] == "Shelf B"

    def test_the_tree_holds_each_location_exactly_once(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        """Every node appears once, at one place.

        Guards a specific trap: the node schema's ``children`` field will
        happily populate itself from the ORM relationship, and the tree is then
        assembled on top of a subtree that already exists — every location
        appearing twice, and a deep store exploding combinatorially.
        """
        roots = client.get("/api/v1/storage/tree", headers=auth_headers(client, "keeper")).json()

        seen: list[str] = []

        def walk(node: dict) -> None:
            seen.append(node["id"])
            for child in node["children"]:
                walk(child)

        for root in roots:
            walk(root)

        assert len(seen) == len(set(seen)), "a location appears more than once in the tree"
        assert set(seen) == {location["id"] for location in store.values()}

    def test_the_tree_reports_one_child_per_parent_here(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        roots = client.get("/api/v1/storage/tree", headers=auth_headers(client, "keeper")).json()

        node = roots[0]
        for _ in range(4):
            assert (
                len(node["children"]) == 1
            ), f"{node['name']} has {len(node['children'])} children"
            node = node["children"][0]
        assert node["children"] == []

    def test_within_finds_the_whole_subtree_and_not_a_similar_name(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        """``/203`` must not also match ``/2030``."""
        add_location(
            client, kind="room", name="Room 2030", code="2030", parent_id=store["building"]["id"]
        )

        inside = client.get(
            "/api/v1/storage/locations",
            params={"within": store["room"]["id"]},
            headers=auth_headers(client, "keeper"),
        ).json()

        names = {item["name"] for item in inside["items"]}
        assert names == {"Cabinet 4", "Shelf B"}
        assert "Room 2030" not in names


# --------------------------------------------------------------------------
# Renaming and moving
# --------------------------------------------------------------------------
class TestReshaping:
    def test_renaming_rewrites_the_path_of_everything_inside(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        headers = auth_headers(client, "keeper")

        renamed = client.patch(
            f"/api/v1/storage/locations/{store['room']['id']}",
            json={"name": "Room 205", "code": "205"},
            headers=headers,
        )
        assert renamed.status_code == 200, renamed.text

        shelf = client.get(
            f"/api/v1/storage/locations/{store['shelf']['id']}", headers=headers
        ).json()
        assert shelf["path"] == "/nm/a/205/cab-4/b"
        assert "Room 205" in shelf["display_path"]
        assert "Room 203" not in shelf["display_path"]

    def test_moving_a_cabinet_takes_its_shelves_with_it(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        headers = auth_headers(client, "keeper")
        other_room = add_location(
            client, kind="room", name="Room 210", code="210", parent_id=store["building"]["id"]
        ).json()

        moved = client.post(
            f"/api/v1/storage/locations/{store['cabinet']['id']}/move",
            json={"parent_id": other_room["id"]},
            headers=headers,
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["path"] == "/nm/a/210/cab-4"

        shelf = client.get(
            f"/api/v1/storage/locations/{store['shelf']['id']}", headers=headers
        ).json()
        assert shelf["path"] == "/nm/a/210/cab-4/b"
        assert "Room 210" in shelf["display_path"]

    def test_a_location_cannot_be_moved_inside_itself(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        response = client.post(
            f"/api/v1/storage/locations/{store['room']['id']}/move",
            json={"parent_id": store["shelf"]["id"]},
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 422
        assert "loop" in response.json()["detail"]

    def test_a_location_cannot_be_its_own_parent(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        response = client.post(
            f"/api/v1/storage/locations/{store['room']['id']}/move",
            json={"parent_id": store["room"]["id"]},
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 422

    def test_a_node_can_be_promoted_to_a_root(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        headers = auth_headers(client, "keeper")

        promoted = client.post(
            f"/api/v1/storage/locations/{store['building']['id']}/move",
            json={"parent_id": None},
            headers=headers,
        )
        assert promoted.status_code == 200
        assert promoted.json()["path"] == "/a"
        assert promoted.json()["depth"] == 0

        shelf = client.get(
            f"/api/v1/storage/locations/{store['shelf']['id']}", headers=headers
        ).json()
        assert shelf["path"] == "/a/203/cab-4/b"


# --------------------------------------------------------------------------
# Deleting
# --------------------------------------------------------------------------
class TestDeleting:
    def test_an_empty_leaf_can_be_deleted(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        response = client.delete(
            f"/api/v1/storage/locations/{store['shelf']['id']}",
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 200

    def test_a_location_holding_other_locations_is_refused(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        response = client.delete(
            f"/api/v1/storage/locations/{store['cabinet']['id']}",
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 409
        assert "still contains" in response.json()["detail"]

    def test_a_location_holding_objects_is_refused(
        self, client: TestClient, keeper: User, store: dict, artifact: dict
    ) -> None:
        headers = auth_headers(client, "keeper")
        client.post(
            f"/api/v1/storage/artifacts/{artifact['id']}/move",
            json={"to_location_id": store["shelf"]["id"], "reason": "accession"},
            headers=headers,
        )

        response = client.delete(
            f"/api/v1/storage/locations/{store['shelf']['id']}", headers=headers
        )
        assert response.status_code == 409
        assert "still holds" in response.json()["detail"]


# --------------------------------------------------------------------------
# The movement register
# --------------------------------------------------------------------------
class TestMovement:
    def test_moving_an_object_files_it_and_records_the_move(
        self, client: TestClient, keeper: User, store: dict, artifact: dict
    ) -> None:
        headers = auth_headers(client, "keeper")

        response = client.post(
            f"/api/v1/storage/artifacts/{artifact['id']}/move",
            json={
                "to_location_id": store["shelf"]["id"],
                "reason": "accession",
                "notes": "Received from the 2024 season",
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        movement = response.json()

        assert movement["from_location_id"] is None
        assert movement["to_location_id"] == store["shelf"]["id"]
        assert movement["reason"] == "accession"
        assert movement["moved_by_label"] == keeper.full_name

        where = client.get(
            f"/api/v1/storage/artifacts/{artifact['id']}/location", headers=headers
        ).json()
        assert where["location_id"] == store["shelf"]["id"]
        assert where["display_path"].endswith("Shelf B")

    def test_the_register_keeps_every_step_in_order(
        self, client: TestClient, keeper: User, store: dict, artifact: dict
    ) -> None:
        headers = auth_headers(client, "keeper")
        lab = add_location(
            client,
            kind="room",
            name="Conservation Lab",
            code="LAB",
            parent_id=store["building"]["id"],
        ).json()

        for destination, reason in (
            (store["shelf"]["id"], "accession"),
            (lab["id"], "conservation"),
            (store["shelf"]["id"], "reorganisation"),
        ):
            response = client.post(
                f"/api/v1/storage/artifacts/{artifact['id']}/move",
                json={"to_location_id": destination, "reason": reason},
                headers=headers,
            )
            assert response.status_code == 201, response.text

        history = client.get(
            f"/api/v1/storage/artifacts/{artifact['id']}/movements", headers=headers
        ).json()

        assert [row["reason"] for row in history] == [
            "accession",
            "conservation",
            "reorganisation",
        ]
        # Each step's origin is the previous step's destination.
        assert history[1]["from_location_id"] == store["shelf"]["id"]
        assert history[2]["from_location_id"] == lab["id"]

    def test_moving_an_object_where_it_already_is_records_nothing(
        self, client: TestClient, keeper: User, store: dict, artifact: dict
    ) -> None:
        headers = auth_headers(client, "keeper")
        body = {"to_location_id": store["shelf"]["id"], "reason": "accession"}

        assert (
            client.post(
                f"/api/v1/storage/artifacts/{artifact['id']}/move", json=body, headers=headers
            ).status_code
            == 201
        )

        repeat = client.post(
            f"/api/v1/storage/artifacts/{artifact['id']}/move", json=body, headers=headers
        )
        assert repeat.status_code == 409

        history = client.get(
            f"/api/v1/storage/artifacts/{artifact['id']}/movements", headers=headers
        ).json()
        assert len(history) == 1, "re-submitting a form must not invent a movement"

    def test_the_register_freezes_the_path_as_it_read_that_day(
        self, client: TestClient, keeper: User, store: dict, artifact: dict
    ) -> None:
        """Renaming a room must not rewrite history."""
        headers = auth_headers(client, "keeper")
        client.post(
            f"/api/v1/storage/artifacts/{artifact['id']}/move",
            json={"to_location_id": store["shelf"]["id"], "reason": "accession"},
            headers=headers,
        )

        client.patch(
            f"/api/v1/storage/locations/{store['room']['id']}",
            json={"name": "Room 999", "code": "999"},
            headers=headers,
        )

        history = client.get(
            f"/api/v1/storage/artifacts/{artifact['id']}/movements", headers=headers
        ).json()
        assert "Room 203" in history[0]["to_path"]
        assert "Room 999" not in history[0]["to_path"]

        # The *current* location does follow the rename — that is the point of
        # the two being different things.
        where = client.get(
            f"/api/v1/storage/artifacts/{artifact['id']}/location", headers=headers
        ).json()
        assert "Room 999" in where["display_path"]

    def test_an_object_can_leave_storage_entirely(
        self, client: TestClient, keeper: User, store: dict, artifact: dict
    ) -> None:
        headers = auth_headers(client, "keeper")
        client.post(
            f"/api/v1/storage/artifacts/{artifact['id']}/move",
            json={"to_location_id": store["shelf"]["id"], "reason": "accession"},
            headers=headers,
        )

        gone = client.post(
            f"/api/v1/storage/artifacts/{artifact['id']}/move",
            json={"to_location_id": None, "reason": "repatriation", "notes": "Returned 2025"},
            headers=headers,
        )
        assert gone.status_code == 201, gone.text
        assert gone.json()["to_location_id"] is None
        assert gone.json()["from_location_id"] == store["shelf"]["id"]

        where = client.get(
            f"/api/v1/storage/artifacts/{artifact['id']}/location", headers=headers
        ).json()
        assert where["location_id"] is None

    def test_a_move_can_be_backdated(
        self, client: TestClient, keeper: User, store: dict, artifact: dict
    ) -> None:
        """A registrar catching up on Friday still records Tuesday's move."""
        when = (datetime.now(UTC) - timedelta(days=3)).replace(microsecond=0)

        response = client.post(
            f"/api/v1/storage/artifacts/{artifact['id']}/move",
            json={
                "to_location_id": store["shelf"]["id"],
                "reason": "accession",
                "moved_at": when.isoformat(),
            },
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 201
        assert response.json()["moved_at"].startswith(when.strftime("%Y-%m-%dT%H:%M"))

    def test_an_inactive_location_stops_accepting_objects(
        self, client: TestClient, keeper: User, store: dict, artifact: dict
    ) -> None:
        headers = auth_headers(client, "keeper")
        client.patch(
            f"/api/v1/storage/locations/{store['shelf']['id']}",
            json={"is_active": False},
            headers=headers,
        )

        response = client.post(
            f"/api/v1/storage/artifacts/{artifact['id']}/move",
            json={"to_location_id": store["shelf"]["id"], "reason": "accession"},
            headers=headers,
        )
        assert response.status_code == 422
        assert "not accepting objects" in response.json()["detail"]

    def test_moving_to_a_location_that_does_not_exist_is_refused(
        self, client: TestClient, keeper: User, artifact: dict
    ) -> None:
        import uuid as uuid_module

        response = client.post(
            f"/api/v1/storage/artifacts/{artifact['id']}/move",
            json={"to_location_id": str(uuid_module.uuid4())},
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 422


# --------------------------------------------------------------------------
# Contents and occupancy
# --------------------------------------------------------------------------
class TestContents:
    def test_a_room_reports_everything_in_its_subtree(
        self, client: TestClient, keeper: User, store: dict, artifact: dict
    ) -> None:
        headers = auth_headers(client, "keeper")
        client.post(
            f"/api/v1/storage/artifacts/{artifact['id']}/move",
            json={"to_location_id": store["shelf"]["id"], "reason": "accession"},
            headers=headers,
        )

        room = client.get(
            f"/api/v1/storage/locations/{store['room']['id']}", headers=headers
        ).json()
        # Nothing is filed directly in the room; one thing is on a shelf in it.
        assert room["object_count"] == 0
        assert room["subtree_object_count"] == 1

        contents = client.get(
            f"/api/v1/storage/locations/{store['room']['id']}/contents", headers=headers
        ).json()
        assert [item["inventory_number"] for item in contents["items"]] == ["ST-2024-001"]

    def test_contents_are_permission_filtered(
        self, client: TestClient, db: Session, keeper: User, store: dict, artifact: dict
    ) -> None:
        """The store is not a way around record permissions."""
        headers = auth_headers(client, "keeper")
        private = client.post(
            "/api/v1/artifacts",
            json={
                "site_id": artifact["site_id"],
                "inventory_number": "ST-2024-SECRET",
                "name": "Unpublished",
                "is_public": False,
            },
            headers=headers,
        ).json()
        for record_id in (artifact["id"], private["id"]):
            client.post(
                f"/api/v1/storage/artifacts/{record_id}/move",
                json={"to_location_id": store["shelf"]["id"], "reason": "accession"},
                headers=headers,
            )

        make_user(
            db,
            email="outsider@example.org",
            username="outsider",
            modules={Module.MUSEUM: ModuleLevel.VIEWER},
        )
        seen = client.get(
            f"/api/v1/storage/locations/{store['shelf']['id']}/contents",
            headers=auth_headers(client, "outsider"),
        ).json()

        numbers = {item["inventory_number"] for item in seen["items"]}
        assert "ST-2024-001" in numbers
        assert "ST-2024-SECRET" not in numbers


# --------------------------------------------------------------------------
# Permissions
# --------------------------------------------------------------------------
class TestStoragePermissions:
    def test_reading_the_store_needs_a_module_that_stores_things(
        self, client: TestClient, db: Session, keeper: User, store: dict
    ) -> None:
        make_user(
            db,
            email="comms@example.org",
            username="comms",
            role=UserRole.VISITOR,
            modules={Module.SOCIAL_MEDIA: ModuleLevel.EDITOR},
            grant_defaults=False,
        )
        response = client.get("/api/v1/storage/tree", headers=auth_headers(client, "comms"))
        assert response.status_code == 403

    def test_museum_access_alone_is_enough_to_read_the_store(
        self, client: TestClient, db: Session, keeper: User, store: dict
    ) -> None:
        make_user(
            db,
            email="curator@example.org",
            username="curator",
            role=UserRole.VISITOR,
            modules={Module.MUSEUM: ModuleLevel.VIEWER},
            grant_defaults=False,
        )
        response = client.get("/api/v1/storage/tree", headers=auth_headers(client, "curator"))
        assert response.status_code == 200
        assert response.json()[0]["name"] == "National Museum"

    def test_reshaping_the_store_needs_a_supervisor(
        self, client: TestClient, db: Session, keeper: User, store: dict
    ) -> None:
        make_user(db, email="digger@example.org", username="digger")  # contributor

        response = add_location(client, kind="room", name="Sneaky", code="SNK", identifier="digger")
        assert response.status_code == 403

    def test_anonymous_callers_cannot_see_the_store(
        self, client: TestClient, keeper: User, store: dict
    ) -> None:
        assert client.get("/api/v1/storage/tree").status_code == 401

    def test_moving_an_object_needs_edit_rights_on_it(
        self, client: TestClient, db: Session, keeper: User, store: dict, artifact: dict
    ) -> None:
        make_user(
            db,
            email="passer@example.org",
            username="passer",
            role=UserRole.RESEARCHER,
        )
        response = client.post(
            f"/api/v1/storage/artifacts/{artifact['id']}/move",
            json={"to_location_id": store["shelf"]["id"]},
            headers=auth_headers(client, "passer"),
        )
        assert response.status_code == 403


# --------------------------------------------------------------------------
# Service-level invariants
# --------------------------------------------------------------------------
class TestTreeService:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("CAB-4", "cab-4"),
            ("Room 203", "room-203"),
            ("  Shelf/B  ", "shelf-b"),
            ("...", "unnamed"),
            ("", "unnamed"),
        ],
    )
    def test_codes_become_path_safe(self, given: str, expected: str) -> None:
        assert tree.slug(given) == expected

    def test_kinds_are_ordered_outermost_to_innermost(self) -> None:
        order = [
            StorageKind.INSTITUTION,
            StorageKind.BUILDING,
            StorageKind.FLOOR,
            StorageKind.ROOM,
            StorageKind.CABINET,
            StorageKind.SHELF,
            StorageKind.DRAWER,
            StorageKind.BOX,
        ]
        assert [kind.depth for kind in order] == sorted(kind.depth for kind in order)
        assert len(order) == len(StorageKind)

    def test_a_rung_may_repeat(self, db: Session, keeper: User) -> None:
        """Finds bags inside a crate really are boxes inside a box."""
        crate = tree.create(db, kind=StorageKind.BOX, name="Crate 1", code="c1")
        bag = tree.create(db, kind=StorageKind.BOX, name="Bag 12", code="b12", parent_id=crate.id)
        assert bag.path == "/c1/b12"

    def test_nesting_is_bounded(self, db: Session, keeper: User) -> None:
        """A bug must not be able to build an unbounded chain."""
        node = tree.create(db, kind=StorageKind.BOX, name="Box 0", code="b0")
        for index in range(1, tree.MAX_DEPTH + 1):
            node = tree.create(
                db,
                kind=StorageKind.BOX,
                name=f"Box {index}",
                code=f"b{index}",
                parent_id=node.id,
            )
        assert node.depth == tree.MAX_DEPTH

        with pytest.raises(tree.StorageError, match="levels deep"):
            tree.create(
                db,
                kind=StorageKind.BOX,
                name="One too many",
                code="over",
                parent_id=node.id,
            )

    def test_a_movement_needs_an_end(self, db: Session, keeper: User) -> None:
        import uuid as uuid_module

        with pytest.raises(tree.StorageError, match="source or a destination"):
            tree.record_movement(
                db,
                resource_type=ResourceType.ARTIFACT,
                resource_id=uuid_module.uuid4(),
                resource_label="Nowhere",
                from_location=None,
                to_location=None,
            )

    def test_the_legacy_free_text_location_is_reported_when_nothing_structured_exists(
        self, client: TestClient, db: Session, keeper: User, artifact: dict
    ) -> None:
        """Honest about what is known, rather than showing an empty field."""
        row = db.get(Artifact, artifact["id"])
        row.current_location = "Field house, Room 2, Shelf B"
        db.add(row)
        db.flush()

        where = client.get(
            f"/api/v1/storage/artifacts/{artifact['id']}/location",
            headers=auth_headers(client, "keeper"),
        ).json()
        assert where["location_id"] is None
        assert where["legacy_location"] == "Field house, Room 2, Shelf B"

    def test_the_legacy_field_is_dropped_once_a_real_location_is_known(
        self, client: TestClient, db: Session, keeper: User, store: dict, artifact: dict
    ) -> None:
        headers = auth_headers(client, "keeper")
        row = db.get(Artifact, artifact["id"])
        row.current_location = "Somewhere vague"
        db.add(row)
        db.flush()

        client.post(
            f"/api/v1/storage/artifacts/{artifact['id']}/move",
            json={"to_location_id": store["shelf"]["id"], "reason": "reorganisation"},
            headers=headers,
        )

        where = client.get(
            f"/api/v1/storage/artifacts/{artifact['id']}/location", headers=headers
        ).json()
        assert where["legacy_location"] is None
        assert where["display_path"].endswith("Shelf B")

    def test_every_movement_reason_is_usable(
        self, client: TestClient, keeper: User, store: dict, artifact: dict
    ) -> None:
        """A closed list is only useful if every value round-trips."""
        headers = auth_headers(client, "keeper")
        shelves = {}
        for index, reason in enumerate(MovementReason):
            shelf = add_location(
                client,
                kind="shelf",
                name=f"Shelf {index}",
                code=f"s{index}",
                parent_id=store["cabinet"]["id"],
            ).json()
            shelves[reason] = shelf

            response = client.post(
                f"/api/v1/storage/artifacts/{artifact['id']}/move",
                json={"to_location_id": shelf["id"], "reason": reason.value},
                headers=headers,
            )
            assert response.status_code == 201, f"{reason.value}: {response.text}"

        history = client.get(
            f"/api/v1/storage/artifacts/{artifact['id']}/movements", headers=headers
        ).json()
        assert [row["reason"] for row in history] == [reason.value for reason in MovementReason]


def test_storage_locations_carry_a_label_token(
    client: TestClient, db: Session, keeper: User, store: dict
) -> None:
    """A shelf gets a printed label like everything else in the building."""
    tokens = {db.get(StorageLocation, location["id"]).public_token for location in store.values()}
    assert len(tokens) == len(store)
    assert all(len(token) == 32 for token in tokens)
