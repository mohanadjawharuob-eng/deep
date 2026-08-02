"""The inventory module: equipment, stock, calibration and kits.

The tests that matter here are the ones about arithmetic and about two people
doing something at once. An inventory that is merely *usually* right is an
inventory somebody stops trusting after the first season, and then stops
using.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Module, ModuleLevel, User, UserRole
from tests.conftest import auth_headers, make_user


@pytest.fixture
def storekeeper(db: Session) -> User:
    """Runs the store. Senior in inventory, absent from everything else."""
    return make_user(
        db,
        email="store@example.org",
        username="storekeeper",
        role=UserRole.VISITOR,
        modules={Module.INVENTORY: ModuleLevel.SUPERVISOR},
        grant_defaults=False,
    )


@pytest.fixture
def digger(db: Session) -> User:
    """A field assistant who may issue kit but not rewrite the register."""
    return make_user(
        db,
        email="digger@example.org",
        username="digger",
        role=UserRole.VISITOR,
        modules={Module.INVENTORY: ModuleLevel.CONTRIBUTOR},
        grant_defaults=False,
    )


@pytest.fixture
def outsider(db: Session) -> User:
    """Somebody with no business in the store at all."""
    return make_user(
        db,
        email="outsider@example.org",
        username="outsider",
        role=UserRole.VISITOR,
        grant_defaults=False,
    )


def add_equipment(client: TestClient, *, who: str = "storekeeper", **fields) -> dict:
    payload = {"asset_number": "EQ-1", "name": "Total station"} | fields
    response = client.post(
        "/api/v1/inventory/equipment", json=payload, headers=auth_headers(client, who)
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_consumable(client: TestClient, *, who: str = "storekeeper", **fields) -> dict:
    payload = {"code": "BAG-S", "name": "Finds bags, small", "unit": "bag"} | fields
    response = client.post(
        "/api/v1/inventory/consumables", json=payload, headers=auth_headers(client, who)
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestEquipment:
    def test_an_item_is_available_when_it_is_added(
        self, client: TestClient, storekeeper: User
    ) -> None:
        item = add_equipment(client)

        assert item["status"] == "available"
        assert item["open_checkout"] is None

    def test_two_items_cannot_share_an_asset_number(
        self, client: TestClient, storekeeper: User
    ) -> None:
        add_equipment(client, asset_number="EQ-7")

        response = client.post(
            "/api/v1/inventory/equipment",
            json={"asset_number": "EQ-7", "name": "Something else"},
            headers=auth_headers(client, "storekeeper"),
        )

        assert response.status_code == 409
        assert "EQ-7" in response.json()["detail"]

    def test_the_store_is_closed_to_people_outside_it(
        self, client: TestClient, storekeeper: User, outsider: User
    ) -> None:
        add_equipment(client)

        response = client.get(
            "/api/v1/inventory/equipment", headers=auth_headers(client, "outsider")
        )

        assert response.json()["total"] == 0, "a private register should show nothing"

    def test_search_matches_the_serial_number(self, client: TestClient, storekeeper: User) -> None:
        """The number on the case is what somebody has in front of them when
        they ring up to ask whose it is."""
        add_equipment(client, asset_number="EQ-2", name="Leica", serial_number="TS-994-B")

        found = client.get(
            "/api/v1/inventory/equipment?q=994", headers=auth_headers(client, "storekeeper")
        ).json()

        assert [row["asset_number"] for row in found["items"]] == ["EQ-2"]


class TestCheckout:
    def test_taking_an_item_out_records_who_has_it(
        self, client: TestClient, storekeeper: User
    ) -> None:
        item = add_equipment(client)

        response = client.post(
            f"/api/v1/inventory/equipment/{item['id']}/checkouts",
            json={"borrower_label": "Rania", "destination": "Trench 4"},
            headers=auth_headers(client, "storekeeper"),
        )

        assert response.status_code == 201, response.text
        assert response.json()["borrower_label"] == "Rania"

        after = client.get(
            f"/api/v1/inventory/equipment/{item['id']}",
            headers=auth_headers(client, "storekeeper"),
        ).json()
        assert after["status"] == "checked_out"
        assert after["open_checkout"]["destination"] == "Trench 4"

    def test_one_item_cannot_be_in_two_places(self, client: TestClient, storekeeper: User) -> None:
        """The whole point of the register. Two people each believing they have
        the theodolite is the failure it exists to prevent."""
        item = add_equipment(client)
        headers = auth_headers(client, "storekeeper")
        client.post(
            f"/api/v1/inventory/equipment/{item['id']}/checkouts",
            json={"borrower_label": "Rania"},
            headers=headers,
        )

        second = client.post(
            f"/api/v1/inventory/equipment/{item['id']}/checkouts",
            json={"borrower_label": "Samir"},
            headers=headers,
        )

        assert second.status_code == 409
        assert "Rania" in second.json()["detail"], "say who has it, not just that it is out"

    def test_an_item_cannot_be_created_already_on_loan(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """It would have no loan behind it, so the register would say the item
        is gone without being able to say who has it."""
        response = client.post(
            "/api/v1/inventory/equipment",
            json={"asset_number": "EQ-9", "name": "Theodolite", "status": "checked_out"},
            headers=auth_headers(client, "storekeeper"),
        )

        assert response.status_code == 422

    def test_the_form_does_not_offer_a_status_the_api_refuses(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """A dropdown holding out an option that always fails is a trap, and
        the frontend renders exactly what the layout says."""
        layout = client.get(
            "/api/v1/forms/layouts/equipment", headers=auth_headers(client, "storekeeper")
        ).json()

        field = next(
            f
            for tab in layout["tabs"]
            for group in tab["groups"]
            for f in group["fields"]
            if f["name"] == "status"
        )
        options = layout["value_list_options"][field["value_list"]]

        assert "checked_out" not in {option["value"] for option in options}
        assert "available" in {option["value"] for option in options}

    def test_the_status_cannot_be_edited_to_checked_out(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """That would record the item as gone without recording who has it."""
        item = add_equipment(client)

        response = client.patch(
            f"/api/v1/inventory/equipment/{item['id']}",
            json={"status": "checked_out"},
            headers=auth_headers(client, "storekeeper"),
        )

        assert response.status_code == 422

    def test_an_item_on_loan_cannot_be_edited_out_of_it(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """Setting it to 'available' by hand would leave the loan open and the
        register saying two different things about where it is."""
        item = add_equipment(client)
        headers = auth_headers(client, "storekeeper")
        client.post(
            f"/api/v1/inventory/equipment/{item['id']}/checkouts",
            json={"borrower_label": "Rania"},
            headers=headers,
        )

        response = client.patch(
            f"/api/v1/inventory/equipment/{item['id']}",
            json={"status": "available"},
            headers=headers,
        )

        assert response.status_code == 409

    def test_returning_puts_it_back_on_the_shelf(
        self, client: TestClient, storekeeper: User
    ) -> None:
        item = add_equipment(client)
        headers = auth_headers(client, "storekeeper")
        checkout = client.post(
            f"/api/v1/inventory/equipment/{item['id']}/checkouts",
            json={"borrower_label": "Rania"},
            headers=headers,
        ).json()

        response = client.post(
            f"/api/v1/inventory/checkouts/{checkout['id']}/return",
            json={"condition_in": "Fine, tripod foot bent"},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        after = client.get(f"/api/v1/inventory/equipment/{item['id']}", headers=headers).json()
        assert after["status"] == "available"
        assert after["open_checkout"] is None

    def test_a_returned_item_can_go_out_again(self, client: TestClient, storekeeper: User) -> None:
        """The constraint is on *open* loans; an item may have been out a
        hundred times before."""
        item = add_equipment(client)
        headers = auth_headers(client, "storekeeper")
        first = client.post(
            f"/api/v1/inventory/equipment/{item['id']}/checkouts",
            json={"borrower_label": "Rania"},
            headers=headers,
        ).json()
        client.post(f"/api/v1/inventory/checkouts/{first['id']}/return", json={}, headers=headers)

        second = client.post(
            f"/api/v1/inventory/equipment/{item['id']}/checkouts",
            json={"borrower_label": "Samir"},
            headers=headers,
        )

        assert second.status_code == 201, second.text

    def test_a_loan_cannot_be_closed_twice(self, client: TestClient, storekeeper: User) -> None:
        item = add_equipment(client)
        headers = auth_headers(client, "storekeeper")
        checkout = client.post(
            f"/api/v1/inventory/equipment/{item['id']}/checkouts",
            json={"borrower_label": "Rania"},
            headers=headers,
        ).json()
        client.post(
            f"/api/v1/inventory/checkouts/{checkout['id']}/return", json={}, headers=headers
        )

        again = client.post(
            f"/api/v1/inventory/checkouts/{checkout['id']}/return", json={}, headers=headers
        )

        assert again.status_code == 409

    def test_the_overdue_list_counts_the_days(self, client: TestClient, storekeeper: User) -> None:
        item = add_equipment(client)
        headers = auth_headers(client, "storekeeper")
        client.post(
            f"/api/v1/inventory/equipment/{item['id']}/checkouts",
            json={
                "borrower_label": "Rania",
                "taken_at": (datetime.now(UTC) - timedelta(days=20)).isoformat(),
                "due_on": (date.today() - timedelta(days=6)).isoformat(),
            },
            headers=headers,
        )

        overdue = client.get(
            "/api/v1/inventory/equipment/out?overdue_only=true", headers=headers
        ).json()

        assert overdue["total"] == 1
        assert overdue["items"][0]["days_overdue"] == 6
        assert overdue["items"][0]["asset_number"] == "EQ-1"

    def test_an_item_out_on_loan_cannot_be_deleted(
        self, client: TestClient, storekeeper: User
    ) -> None:
        item = add_equipment(client)
        headers = auth_headers(client, "storekeeper")
        client.post(
            f"/api/v1/inventory/equipment/{item['id']}/checkouts",
            json={"borrower_label": "Rania"},
            headers=headers,
        )

        response = client.delete(f"/api/v1/inventory/equipment/{item['id']}", headers=headers)

        assert response.status_code == 409

    def test_a_borrower_has_to_be_named(self, client: TestClient, storekeeper: User) -> None:
        item = add_equipment(client)

        response = client.post(
            f"/api/v1/inventory/equipment/{item['id']}/checkouts",
            json={"destination": "Trench 4"},
            headers=auth_headers(client, "storekeeper"),
        )

        assert response.status_code == 422


class TestStock:
    def test_the_opening_quantity_starts_the_ledger(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """A total with nothing behind it is a total nobody can check."""
        stock = add_consumable(client, opening_quantity=500)

        assert float(stock["quantity"]) == 500
        ledger = client.get(
            f"/api/v1/inventory/consumables/{stock['id']}/movements",
            headers=auth_headers(client, "storekeeper"),
        ).json()
        assert ledger["total"] == 1
        assert float(ledger["items"][0]["balance_after"]) == 500

    def test_issuing_stock_lowers_the_total_and_is_written_down(
        self, client: TestClient, storekeeper: User
    ) -> None:
        stock = add_consumable(client, opening_quantity=500)
        headers = auth_headers(client, "storekeeper")

        response = client.post(
            f"/api/v1/inventory/consumables/{stock['id']}/movements",
            json={"change": -120, "reason": "issued", "issued_to_label": "Trench 4"},
            headers=headers,
        )

        assert response.status_code == 201, response.text
        assert float(response.json()["balance_after"]) == 380
        after = client.get(f"/api/v1/inventory/consumables/{stock['id']}", headers=headers).json()
        assert float(after["quantity"]) == 380

    def test_the_shelf_cannot_hold_less_than_nothing(
        self, client: TestClient, storekeeper: User
    ) -> None:
        stock = add_consumable(client, opening_quantity=10)

        response = client.post(
            f"/api/v1/inventory/consumables/{stock['id']}/movements",
            json={"change": -11, "reason": "issued"},
            headers=auth_headers(client, "storekeeper"),
        )

        assert response.status_code == 409
        assert "10" in response.json()["detail"], "say how many there actually are"

    def test_the_quantity_cannot_be_typed_over(self, client: TestClient, storekeeper: User) -> None:
        """If a PATCH could set the total, the ledger behind it would be
        decorative."""
        stock = add_consumable(client, opening_quantity=100)

        client.patch(
            f"/api/v1/inventory/consumables/{stock['id']}",
            json={"quantity": 999},
            headers=auth_headers(client, "storekeeper"),
        )

        after = client.get(
            f"/api/v1/inventory/consumables/{stock['id']}",
            headers=auth_headers(client, "storekeeper"),
        ).json()
        assert float(after["quantity"]) == 100

    def test_a_stock_take_records_the_difference_as_an_event(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """A discrepancy somebody can ask about, rather than a number that
        quietly changed."""
        stock = add_consumable(client, opening_quantity=500)
        headers = auth_headers(client, "storekeeper")

        response = client.post(
            f"/api/v1/inventory/consumables/{stock['id']}/stock-take",
            json={"counted": 460},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert float(response.json()["change"]) == -40
        assert response.json()["reason"] == "stocktake"

    def test_a_stock_take_that_agrees_writes_nothing(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """An inventory full of zero-change rows is an inventory nobody reads."""
        stock = add_consumable(client, opening_quantity=500)
        headers = auth_headers(client, "storekeeper")

        client.post(
            f"/api/v1/inventory/consumables/{stock['id']}/stock-take",
            json={"counted": 500},
            headers=headers,
        )

        ledger = client.get(
            f"/api/v1/inventory/consumables/{stock['id']}/movements", headers=headers
        ).json()
        assert ledger["total"] == 1, "only the opening movement"

    def test_the_ledger_adds_up_to_the_total(self, client: TestClient, storekeeper: User) -> None:
        """The invariant the whole design rests on."""
        stock = add_consumable(client, opening_quantity=500)
        headers = auth_headers(client, "storekeeper")
        for change in (-120, 200, -35, -5):
            client.post(
                f"/api/v1/inventory/consumables/{stock['id']}/movements",
                json={"change": change, "reason": "issued" if change < 0 else "received"},
                headers=headers,
            )

        ledger = client.get(
            f"/api/v1/inventory/consumables/{stock['id']}/movements", headers=headers
        ).json()
        total = client.get(f"/api/v1/inventory/consumables/{stock['id']}", headers=headers).json()

        assert sum(float(row["change"]) for row in ledger["items"]) == float(total["quantity"])
        assert float(total["quantity"]) == 540

    def test_the_reorder_list_is_what_is_running_out(
        self, client: TestClient, storekeeper: User
    ) -> None:
        add_consumable(client, code="BAG-S", opening_quantity=40, reorder_level=100)
        add_consumable(client, code="BAG-L", opening_quantity=400, reorder_level=100)

        low = client.get(
            "/api/v1/inventory/consumables?needs_reorder=true",
            headers=auth_headers(client, "storekeeper"),
        ).json()

        assert [row["code"] for row in low["items"]] == ["BAG-S"]

    def test_fractional_stock_survives_the_round_trip(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """Permatrace is measured, not counted, and floating point is not a
        thing to keep an inventory in."""
        stock = add_consumable(client, code="PERMA", unit="metre", opening_quantity=12.5)
        headers = auth_headers(client, "storekeeper")

        client.post(
            f"/api/v1/inventory/consumables/{stock['id']}/movements",
            json={"change": -0.3, "reason": "used"},
            headers=headers,
        )

        after = client.get(f"/api/v1/inventory/consumables/{stock['id']}", headers=headers).json()
        assert float(after["quantity"]) == 12.2


class TestCalibration:
    def test_the_due_date_comes_from_the_interval(
        self, client: TestClient, storekeeper: User
    ) -> None:
        item = add_equipment(client, needs_calibration=True, calibration_interval_days=365)
        headers = auth_headers(client, "storekeeper")
        performed = date.today() - timedelta(days=10)

        response = client.post(
            f"/api/v1/inventory/equipment/{item['id']}/calibrations",
            json={"performed_on": performed.isoformat(), "result": "passed"},
            headers=headers,
        )

        assert response.status_code == 201, response.text
        assert response.json()["next_due_on"] == (performed + timedelta(days=365)).isoformat()

    def test_the_certificate_beats_the_interval(
        self, client: TestClient, storekeeper: User
    ) -> None:
        item = add_equipment(client, needs_calibration=True, calibration_interval_days=365)
        given = date.today() + timedelta(days=90)

        response = client.post(
            f"/api/v1/inventory/equipment/{item['id']}/calibrations",
            json={
                "performed_on": date.today().isoformat(),
                "next_due_on": given.isoformat(),
                "result": "passed",
            },
            headers=auth_headers(client, "storekeeper"),
        )

        assert response.json()["next_due_on"] == given.isoformat()

    def test_an_old_certificate_does_not_move_the_due_date_backwards(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """Entering one found in a drawer is a normal thing to do, and must not
        make an item that is currently in date look overdue."""
        item = add_equipment(client, needs_calibration=True, calibration_interval_days=365)
        headers = auth_headers(client, "storekeeper")
        client.post(
            f"/api/v1/inventory/equipment/{item['id']}/calibrations",
            json={"performed_on": date.today().isoformat(), "result": "passed"},
            headers=headers,
        )
        current = client.get(f"/api/v1/inventory/equipment/{item['id']}", headers=headers).json()[
            "calibration_due_on"
        ]

        client.post(
            f"/api/v1/inventory/equipment/{item['id']}/calibrations",
            json={
                "performed_on": (date.today() - timedelta(days=800)).isoformat(),
                "result": "passed",
            },
            headers=headers,
        )

        after = client.get(f"/api/v1/inventory/equipment/{item['id']}", headers=headers).json()
        assert after["calibration_due_on"] == current
        assert after["calibration_overdue"] is False

    def test_a_failed_calibration_takes_the_item_out_of_service(
        self, client: TestClient, storekeeper: User
    ) -> None:
        item = add_equipment(client, needs_calibration=True)
        headers = auth_headers(client, "storekeeper")

        client.post(
            f"/api/v1/inventory/equipment/{item['id']}/calibrations",
            json={"performed_on": date.today().isoformat(), "result": "failed"},
            headers=headers,
        )

        after = client.get(f"/api/v1/inventory/equipment/{item['id']}", headers=headers).json()
        assert after["status"] == "in_repair"

    def test_an_expired_certificate_shows_as_overdue(
        self, client: TestClient, storekeeper: User
    ) -> None:
        item = add_equipment(client, needs_calibration=True, calibration_interval_days=30)
        headers = auth_headers(client, "storekeeper")
        client.post(
            f"/api/v1/inventory/equipment/{item['id']}/calibrations",
            json={
                "performed_on": (date.today() - timedelta(days=100)).isoformat(),
                "result": "passed",
            },
            headers=headers,
        )

        detail = client.get(f"/api/v1/inventory/equipment/{item['id']}", headers=headers).json()
        listed = client.get(
            "/api/v1/inventory/equipment?calibration_overdue=true", headers=headers
        ).json()

        assert detail["calibration_overdue"] is True
        assert listed["total"] == 1

    def test_a_calibration_cannot_be_in_the_future(
        self, client: TestClient, storekeeper: User
    ) -> None:
        item = add_equipment(client)

        response = client.post(
            f"/api/v1/inventory/equipment/{item['id']}/calibrations",
            json={
                "performed_on": (date.today() + timedelta(days=1)).isoformat(),
                "result": "passed",
            },
            headers=auth_headers(client, "storekeeper"),
        )

        assert response.status_code == 422


class TestKitBuilder:
    def _template(self, client: TestClient, lines: list[dict], name: str = "Trench kit") -> dict:
        response = client.post(
            "/api/v1/inventory/kit-templates",
            json={"name": name, "lines": lines},
            headers=auth_headers(client, "storekeeper"),
        )
        assert response.status_code == 201, response.text
        return response.json()

    def test_a_line_names_exactly_one_thing(self, client: TestClient, storekeeper: User) -> None:
        """A line naming both a specific item and a category cannot be filled
        without guessing which the author meant."""
        item = add_equipment(client)

        response = client.post(
            "/api/v1/inventory/kit-templates",
            json={
                "name": "Confused",
                "lines": [{"equipment_id": item["id"], "equipment_category": "camera"}],
            },
            headers=auth_headers(client, "storekeeper"),
        )

        assert response.status_code == 422

    def test_building_takes_the_kit_out_of_the_door(
        self, client: TestClient, storekeeper: User
    ) -> None:
        item = add_equipment(client, asset_number="EQ-1", name="Leica", category="total station")
        bags = add_consumable(client, opening_quantity=500)
        template = self._template(
            client,
            [
                {"equipment_category": "total station", "quantity": 1},
                {"consumable_id": bags["id"], "quantity": 100},
            ],
        )
        headers = auth_headers(client, "storekeeper")

        response = client.post(
            f"/api/v1/inventory/kit-templates/{template['id']}/build",
            json={"issued_to_label": "Rania", "destination": "Trench 4"},
            headers=headers,
        )

        assert response.status_code == 201, response.text
        kit = response.json()
        assert kit["shortfalls"] == []
        assert [entry["asset_number"] for entry in kit["checkouts"]] == ["EQ-1"]

        # The equipment is out and the stock has gone down, in one action.
        assert (
            client.get(f"/api/v1/inventory/equipment/{item['id']}", headers=headers).json()[
                "status"
            ]
            == "checked_out"
        )
        assert (
            float(
                client.get(f"/api/v1/inventory/consumables/{bags['id']}", headers=headers).json()[
                    "quantity"
                ]
            )
            == 400
        )

    def test_a_shortfall_is_reported_rather_than_raised(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """A kit that is nine tenths ready is still the kit going out this
        morning. The list is what somebody reads before they drive off."""
        bags = add_consumable(client, opening_quantity=30)
        template = self._template(
            client,
            [
                {"consumable_id": bags["id"], "quantity": 100},
                {"equipment_category": "camera", "quantity": 2},
            ],
        )

        response = client.post(
            f"/api/v1/inventory/kit-templates/{template['id']}/build",
            json={"issued_to_label": "Rania"},
            headers=auth_headers(client, "storekeeper"),
        )

        assert response.status_code == 201, response.text
        shortfalls = {entry["what"]: entry for entry in response.json()["shortfalls"]}
        assert len(shortfalls) == 2
        assert shortfalls["camera"]["supplied"] == 0
        # What there was still went out: thirty bags beats no bags.
        bag_line = next(key for key in shortfalls if key.startswith("BAG-S"))
        assert shortfalls[bag_line]["supplied"] == 30
        assert shortfalls[bag_line]["wanted"] == 100

    def test_all_or_nothing_leaves_the_shelves_untouched(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """The interesting half of the flag: a refused build must not have
        issued the lines it managed before it hit the one it could not."""
        bags = add_consumable(client, opening_quantity=500)
        template = self._template(
            client,
            [
                {"consumable_id": bags["id"], "quantity": 100},
                {"equipment_category": "camera", "quantity": 2},
            ],
        )
        headers = auth_headers(client, "storekeeper")

        response = client.post(
            f"/api/v1/inventory/kit-templates/{template['id']}/build",
            json={"issued_to_label": "Rania", "all_or_nothing": True},
            headers=headers,
        )

        assert response.status_code == 409
        after = client.get(f"/api/v1/inventory/consumables/{bags['id']}", headers=headers).json()
        assert float(after["quantity"]) == 500, "the bags should never have left the shelf"
        assert client.get("/api/v1/inventory/kits", headers=headers).json()["total"] == 0

    def test_an_optional_line_does_not_hold_up_the_van(
        self, client: TestClient, storekeeper: User
    ) -> None:
        template = self._template(
            client, [{"equipment_category": "drone", "quantity": 1, "is_optional": True}]
        )

        response = client.post(
            f"/api/v1/inventory/kit-templates/{template['id']}/build",
            json={"issued_to_label": "Rania", "all_or_nothing": True},
            headers=auth_headers(client, "storekeeper"),
        )

        assert response.status_code == 201, response.text
        assert response.json()["shortfalls"][0]["is_optional"] is True

    def test_two_lines_wanting_a_camera_get_different_cameras(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """Both being handed the same one is the obvious bug, and it would show
        up as a kit that is short without saying so."""
        add_equipment(client, asset_number="CAM-1", name="Camera 1", category="camera")
        add_equipment(client, asset_number="CAM-2", name="Camera 2", category="camera")
        template = self._template(
            client,
            [
                {"equipment_category": "camera", "quantity": 1},
                {"equipment_category": "camera", "quantity": 1},
            ],
        )

        kit = client.post(
            f"/api/v1/inventory/kit-templates/{template['id']}/build",
            json={"issued_to_label": "Rania"},
            headers=auth_headers(client, "storekeeper"),
        ).json()

        issued = sorted(entry["asset_number"] for entry in kit["checkouts"])
        assert issued == ["CAM-1", "CAM-2"]
        assert kit["shortfalls"] == []

    def test_an_item_already_out_is_not_handed_out_twice(
        self, client: TestClient, storekeeper: User
    ) -> None:
        item = add_equipment(client, asset_number="CAM-1", category="camera")
        headers = auth_headers(client, "storekeeper")
        client.post(
            f"/api/v1/inventory/equipment/{item['id']}/checkouts",
            json={"borrower_label": "Samir"},
            headers=headers,
        )
        template = self._template(client, [{"equipment_id": item["id"], "quantity": 1}])

        kit = client.post(
            f"/api/v1/inventory/kit-templates/{template['id']}/build",
            json={"issued_to_label": "Rania"},
            headers=headers,
        ).json()

        assert kit["checkouts"] == []
        assert "Samir" in kit["shortfalls"][0]["reason"]

    def test_returning_a_kit_brings_back_everything_in_it(
        self, client: TestClient, storekeeper: User
    ) -> None:
        add_equipment(client, asset_number="CAM-1", category="camera")
        add_equipment(client, asset_number="CAM-2", category="camera")
        template = self._template(client, [{"equipment_category": "camera", "quantity": 2}])
        headers = auth_headers(client, "storekeeper")
        kit = client.post(
            f"/api/v1/inventory/kit-templates/{template['id']}/build",
            json={"issued_to_label": "Rania"},
            headers=headers,
        ).json()

        response = client.post(
            f"/api/v1/inventory/kits/{kit['id']}/return", json={}, headers=headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["outstanding_items"] == 0
        out = client.get("/api/v1/inventory/equipment/out", headers=headers).json()
        assert out["total"] == 0

    def test_a_kit_says_what_was_issued_not_just_how_much(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """ "50 issued" is not a sentence. The movement rows are shown away from
        their own stock line, so they have to carry its name."""
        bags = add_consumable(client, opening_quantity=500)
        template = self._template(client, [{"consumable_id": bags["id"], "quantity": 50}])

        kit = client.post(
            f"/api/v1/inventory/kit-templates/{template['id']}/build",
            json={"issued_to_label": "Rania"},
            headers=auth_headers(client, "storekeeper"),
        ).json()

        issued = kit["stock_movements"][0]
        assert issued["consumable_name"] == "Finds bags, small"
        assert issued["consumable_code"] == "BAG-S"
        assert issued["unit"] == "bag"

    def test_consumables_do_not_come_back_with_the_kit(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """That is what makes them consumables."""
        bags = add_consumable(client, opening_quantity=500)
        template = self._template(client, [{"consumable_id": bags["id"], "quantity": 100}])
        headers = auth_headers(client, "storekeeper")
        kit = client.post(
            f"/api/v1/inventory/kit-templates/{template['id']}/build",
            json={"issued_to_label": "Rania"},
            headers=headers,
        ).json()

        client.post(f"/api/v1/inventory/kits/{kit['id']}/return", json={}, headers=headers)

        after = client.get(f"/api/v1/inventory/consumables/{bags['id']}", headers=headers).json()
        assert float(after["quantity"]) == 400

    def test_quantities_are_written_the_way_people_write_them(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """The column is Numeric(12, 3) so measured stock survives, and
        PostgreSQL hands back all three places. Formatting a Decimal with `:g`
        does not strip them, so "one camera" comes out as "1.000 × camera" and
        the packing list reads like a lab report."""
        bags = add_consumable(client, opening_quantity=10)
        template = self._template(
            client,
            [
                {"equipment_category": "camera", "quantity": 1},
                {"consumable_id": bags["id"], "quantity": 12.5},
            ],
        )

        labels = [line["label"] for line in template["lines"]]

        assert labels[0] == "1 × camera"
        assert labels[1].startswith("12.5 bag")

    def test_a_shortfall_says_how_many_are_actually_there(
        self, client: TestClient, storekeeper: User
    ) -> None:
        bags = add_consumable(client, opening_quantity=3)
        template = self._template(client, [{"consumable_id": bags["id"], "quantity": 100}])

        kit = client.post(
            f"/api/v1/inventory/kit-templates/{template['id']}/build",
            json={"issued_to_label": "Rania"},
            headers=auth_headers(client, "storekeeper"),
        ).json()

        assert "only 3 bag on the shelf" in kit["shortfalls"][0]["reason"]

    def test_a_packing_list_reads_as_words(self, client: TestClient, storekeeper: User) -> None:
        """A template of raw identifiers is a template nobody can check."""
        add_equipment(client, asset_number="EQ-9", name="Dumpy level")
        bags = add_consumable(client, opening_quantity=10)
        template = self._template(
            client,
            [
                {"equipment_category": "camera", "quantity": 2},
                {"consumable_id": bags["id"], "quantity": 100},
            ],
        )

        labels = [line["label"] for line in template["lines"]]

        assert labels[0] == "2 × camera"
        assert "Finds bags, small" in labels[1]

    def test_a_contributor_may_issue_but_not_delete(
        self, client: TestClient, storekeeper: User, digger: User
    ) -> None:
        item = add_equipment(client)

        issued = client.post(
            f"/api/v1/inventory/equipment/{item['id']}/checkouts",
            json={"borrower_label": "Rania"},
            headers=auth_headers(client, "digger"),
        )
        deleted = client.delete(
            f"/api/v1/inventory/equipment/{item['id']}", headers=auth_headers(client, "digger")
        )

        assert issued.status_code == 201, issued.text
        assert deleted.status_code == 403


class TestLayouts:
    """The forms the frontend renders from.

    The frontend does not decide what an equipment card looks like — it draws
    what the layout says. That makes a wrong layout a wrong screen, with no
    error anywhere, so the invariants are worth asserting here.
    """

    def test_every_field_on_a_layout_exists_on_its_record(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """A layout naming a field the model does not have is a form that
        cannot be saved, and the importer would offer the same dead column."""
        from app.models.inventory import Consumable, Equipment
        from app.services import forms

        for record_type, model in (("equipment", Equipment), ("consumable", Consumable)):
            layout = forms.get_layout(record_type)
            assert layout is not None
            columns = {column.key for column in model.__table__.columns}
            for name in forms.field_index(layout):
                assert name in columns, f"{record_type}.{name} is on the form but not on the record"

    def test_every_value_list_a_layout_asks_for_can_be_resolved(
        self, client: TestClient, db: Session, storekeeper: User
    ) -> None:
        """An unresolvable name is skipped in silence, which reaches the
        cataloguer as a dropdown that is simply empty — with nothing anywhere
        saying why."""
        from app.services import forms

        for record_type in forms.LAYOUTS:
            layout = forms.get_layout(record_type)
            assert layout is not None
            resolved = forms.value_lists(db, layout.value_lists)
            missing = [name for name in layout.value_lists if name not in resolved]
            assert not missing, f"{record_type} asks for {missing}, which nothing resolves"

    def test_the_layouts_are_served(self, client: TestClient, storekeeper: User) -> None:
        headers = auth_headers(client, "storekeeper")

        equipment = client.get("/api/v1/forms/layouts/equipment", headers=headers)
        consumable = client.get("/api/v1/forms/layouts/consumable", headers=headers)

        assert equipment.status_code == 200, equipment.text
        assert consumable.status_code == 200, consumable.text
        assert equipment.json()["key_field"] == "asset_number"
        assert [
            option["value"]
            for option in equipment.json()["value_list_options"]["equipment_status_settable"]
        ]

    def test_the_stock_total_is_read_only_on_the_form(
        self, client: TestClient, storekeeper: User
    ) -> None:
        """The form has to agree with the API, which refuses to set it."""
        from app.services import forms

        layout = forms.get_layout("consumable")
        assert layout is not None

        assert forms.field_index(layout)["quantity"].read_only is True
