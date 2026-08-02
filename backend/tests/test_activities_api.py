"""The activity hub, and the calendar it feeds.

Three things here are worth more than the rest of the coverage put together,
because each one is a place where being nearly right is worse than being
absent:

**The repeat.** Copying a season forwards is the module's whole purpose. If a
granted permit came across still granted, somebody would turn up on site with
paperwork for the wrong year; if last year's prices came across as facts rather
than estimates, a budget would be built on them.

**The costs.** Currencies are never summed together, and the estimated part of
a total is always separable from the invoiced part. A figure that quietly mixes
either is a figure a funder eventually audits.

**The calendar being open.** The whole point of the change is that anybody
signed in can add a day. The tests hold both halves of that: everybody may add,
and nobody may quietly rewrite somebody else's entry.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Module, ModuleLevel, User, UserRole
from tests.conftest import auth_headers, make_user


@pytest.fixture
def keeper(db: Session) -> User:
    """Runs the hub. Senior in activities, absent from everything else."""
    return make_user(
        db,
        email="keeper@example.org",
        username="keeper",
        role=UserRole.VISITOR,
        modules={Module.ACTIVITIES: ModuleLevel.SUPERVISOR},
        grant_defaults=False,
    )


@pytest.fixture
def helper(db: Session) -> User:
    """May record activities and edit their own, not delete anyone's."""
    return make_user(
        db,
        email="helper@example.org",
        username="helper",
        role=UserRole.VISITOR,
        modules={Module.ACTIVITIES: ModuleLevel.CONTRIBUTOR},
        grant_defaults=False,
    )


@pytest.fixture
def outsider(db: Session) -> User:
    """Signed in, with no access to the hub at all."""
    return make_user(
        db,
        email="outsider@example.org",
        username="outsider",
        role=UserRole.VISITOR,
        grant_defaults=False,
    )


def add_activity(client: TestClient, *, who: str = "keeper", **fields) -> dict:
    payload = {"title": "North trench, 2019", "kind": "excavation"} | fields
    response = client.post("/api/v1/activities", json=payload, headers=auth_headers(client, who))
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------
# Recording one
# --------------------------------------------------------------------------
class TestRecording:
    def test_an_activity_can_be_recorded_with_only_a_title(
        self, client: TestClient, keeper: User
    ) -> None:
        body = add_activity(client, title="Store reorganisation")
        assert body["title"] == "Store reorganisation"
        assert body["status"] == "planned"
        assert body["outstanding"]["is_clear"] is True

    def test_dates_give_a_duration_counted_inclusively(
        self, client: TestClient, keeper: User
    ) -> None:
        body = add_activity(client, starts_on="2019-06-01", ends_on="2019-06-12")
        # Twelve days, not eleven: a season that runs the first to the twelfth
        # is twelve days of somebody's time and twelve days of vehicle hire.
        assert body["duration_days"] == 12

    def test_an_activity_cannot_end_before_it_starts(
        self, client: TestClient, keeper: User
    ) -> None:
        response = client.post(
            "/api/v1/activities",
            json={"title": "Impossible", "starts_on": "2019-06-12", "ends_on": "2019-06-01"},
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 422

    def test_naming_a_lead_fills_in_their_name(
        self, client: TestClient, keeper: User, researcher: User
    ) -> None:
        body = add_activity(client, lead_id=str(researcher.id))
        assert body["lead_label"] == (researcher.full_name or researcher.username)

    def test_somebody_with_no_access_to_the_hub_cannot_record_one(
        self, client: TestClient, outsider: User
    ) -> None:
        response = client.post(
            "/api/v1/activities",
            json={"title": "Not mine to add"},
            headers=auth_headers(client, "outsider"),
        )
        assert response.status_code == 403

    def test_a_contributor_may_edit_their_own_and_not_anothers(
        self, client: TestClient, keeper: User, helper: User
    ) -> None:
        theirs = add_activity(client, who="helper", title="Helper's survey")
        response = client.patch(
            f"/api/v1/activities/{theirs['id']}",
            json={"summary": "Two days of fieldwalking"},
            headers=auth_headers(client, "helper"),
        )
        assert response.status_code == 200

        somebody_elses = add_activity(client, who="keeper")
        response = client.patch(
            f"/api/v1/activities/{somebody_elses['id']}",
            json={"summary": "Not mine to write"},
            headers=auth_headers(client, "helper"),
        )
        assert response.status_code == 403

    def test_only_a_supervisor_deletes(
        self, client: TestClient, keeper: User, helper: User
    ) -> None:
        theirs = add_activity(client, who="helper")
        assert (
            client.delete(
                f"/api/v1/activities/{theirs['id']}", headers=auth_headers(client, "helper")
            ).status_code
            == 403
        )
        assert (
            client.delete(
                f"/api/v1/activities/{theirs['id']}", headers=auth_headers(client, "keeper")
            ).status_code
            == 200
        )


# --------------------------------------------------------------------------
# The kit list
# --------------------------------------------------------------------------
class TestEquipment:
    def test_a_line_can_be_free_text(self, client: TestClient, keeper: User) -> None:
        activity = add_activity(client)
        response = client.post(
            f"/api/v1/activities/{activity['id']}/equipment",
            json={"label": "Borrowed generator", "quantity": 1, "source": "borrowed"},
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["label"] == "Borrowed generator"
        assert body["equipment_id"] is None

    def test_a_line_naming_nothing_at_all_is_refused(
        self, client: TestClient, keeper: User
    ) -> None:
        activity = add_activity(client)
        response = client.post(
            f"/api/v1/activities/{activity['id']}/equipment",
            json={"quantity": 2},
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 422

    def test_linking_to_the_inventory_copies_the_name(
        self, client: TestClient, keeper: User, admin: User
    ) -> None:
        kit = client.post(
            "/api/v1/inventory/equipment",
            json={"asset_number": "TS-001", "name": "Leica total station"},
            headers=auth_headers(client, "admin"),
        )
        assert kit.status_code == 201, kit.text

        activity = add_activity(client)
        response = client.post(
            f"/api/v1/activities/{activity['id']}/equipment",
            json={"equipment_id": kit.json()["id"]},
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        # Copied onto the line, so the kit list still reads correctly after the
        # item is renamed or retired — and echoed back from the inventory too.
        assert body["label"] == "Leica total station"
        assert body["equipment_name"] == "Leica total station"
        assert body["asset_number"] == "TS-001"
        assert body["equipment_exists"] is True

    def test_a_line_cannot_be_moved_between_activities_by_guessing_its_id(
        self, client: TestClient, keeper: User
    ) -> None:
        one = add_activity(client, title="One")
        two = add_activity(client, title="Two")
        line = client.post(
            f"/api/v1/activities/{one['id']}/equipment",
            json={"label": "Trowel"},
            headers=auth_headers(client, "keeper"),
        ).json()

        response = client.patch(
            f"/api/v1/activities/{two['id']}/equipment/{line['id']}",
            json={"label": "Stolen"},
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 404


# --------------------------------------------------------------------------
# Permits, and the lead times that are the point of them
# --------------------------------------------------------------------------
class TestPermits:
    def test_the_lead_time_is_learned_from_the_dates(
        self, client: TestClient, keeper: User
    ) -> None:
        activity = add_activity(client)
        response = client.post(
            f"/api/v1/activities/{activity['id']}/permits",
            json={
                "name": "Excavation licence",
                "issuer": "Department of Antiquities",
                "status": "granted",
                "applied_on": "2019-02-01",
                "granted_on": "2019-03-19",
            },
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["days_to_obtain"] == 46
        # Nobody typed a lead time, so the dates supplied one. This is the
        # single most useful number the hub holds.
        assert body["lead_time_days"] == 46

    def test_a_typed_lead_time_is_never_overwritten_by_the_dates(
        self, client: TestClient, keeper: User
    ) -> None:
        activity = add_activity(client)
        response = client.post(
            f"/api/v1/activities/{activity['id']}/permits",
            json={
                "name": "Excavation licence",
                "status": "granted",
                "applied_on": "2019-02-01",
                "granted_on": "2019-03-19",
                # Somebody who knows the ministry is slower before Ramadan.
                "lead_time_days": 90,
            },
            headers=auth_headers(client, "keeper"),
        )
        assert response.json()["lead_time_days"] == 90

    def test_marking_it_granted_records_the_day(self, client: TestClient, keeper: User) -> None:
        activity = add_activity(client)
        permit = client.post(
            f"/api/v1/activities/{activity['id']}/permits",
            json={"name": "Landowner's consent", "status": "applied", "applied_on": "2019-01-05"},
            headers=auth_headers(client, "keeper"),
        ).json()

        response = client.patch(
            f"/api/v1/activities/{activity['id']}/permits/{permit['id']}",
            json={"status": "granted"},
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 200
        assert response.json()["granted_on"] == date.today().isoformat()

    def test_it_cannot_be_granted_before_it_was_applied_for(
        self, client: TestClient, keeper: User
    ) -> None:
        activity = add_activity(client)
        response = client.post(
            f"/api/v1/activities/{activity['id']}/permits",
            json={"name": "Backwards", "applied_on": "2019-03-01", "granted_on": "2019-02-01"},
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 422

    def test_a_refusal_is_not_listed_as_outstanding_work(
        self, client: TestClient, keeper: User
    ) -> None:
        activity = add_activity(client)
        for name, permit_status in (("Refused one", "refused"), ("Waiting one", "applied")):
            client.post(
                f"/api/v1/activities/{activity['id']}/permits",
                json={"name": name, "status": permit_status},
                headers=auth_headers(client, "keeper"),
            )

        body = client.get(
            f"/api/v1/activities/{activity['id']}", headers=auth_headers(client, "keeper")
        ).json()
        outstanding = body["outstanding"]["permits"]
        assert any("Waiting one" in entry for entry in outstanding)
        # A refusal is a decision, not a to-do. Listing it would have somebody
        # re-apply into the same no.
        assert not any("Refused one" in entry for entry in outstanding)

    def test_a_finished_season_is_never_told_it_is_running_out_of_time(
        self, client: TestClient, keeper: User
    ) -> None:
        """The bug this pins was visible only by looking at the screen.

        A completed 2019 excavation with an unrenewed insurance policy was
        being shown "not enough time left — normally needs 45 days", measured
        against today. It is a warning that cannot be acted on, about a season
        that is over, and warnings like it are how people learn to ignore the
        colour altogether.
        """
        activity = add_activity(
            client, title="Long finished", starts_on="2019-06-01", ends_on="2019-06-12"
        )
        client.post(
            f"/api/v1/activities/{activity['id']}/preparations",
            json={"description": "Renew the site insurance", "lead_time_days": 45},
            headers=auth_headers(client, "keeper"),
        )
        client.patch(
            f"/api/v1/activities/{activity['id']}",
            json={"status": "completed"},
            headers=auth_headers(client, "keeper"),
        )

        body = client.get(
            f"/api/v1/activities/{activity['id']}", headers=auth_headers(client, "keeper")
        ).json()
        outstanding = body["outstanding"]
        # Still listed — "the insurance was never renewed" is a fact about that
        # season somebody may need…
        assert outstanding["preparations"] == ["Renew the site insurance"]
        # …but nothing about it is late, and the screen is told so.
        assert outstanding["too_late"] == []
        assert outstanding["is_actionable"] is False

        text = client.get(
            f"/api/v1/activities/{activity['id']}/brief.txt",
            headers=auth_headers(client, "keeper"),
        ).text
        assert "NEVER DONE" in text
        assert "Not enough time left" not in text

    def test_a_permit_whose_lead_time_no_longer_fits_is_flagged(
        self, client: TestClient, keeper: User
    ) -> None:
        soon = (date.today() + timedelta(days=10)).isoformat()
        activity = add_activity(client, starts_on=soon)
        client.post(
            f"/api/v1/activities/{activity['id']}/permits",
            json={"name": "Excavation licence", "status": "to_apply", "lead_time_days": 46},
            headers=auth_headers(client, "keeper"),
        )

        body = client.get(
            f"/api/v1/activities/{activity['id']}", headers=auth_headers(client, "keeper")
        ).json()
        assert any("Excavation licence" in entry for entry in body["outstanding"]["too_late"])
        assert body["outstanding"]["longest_lead_days"] == 46


# --------------------------------------------------------------------------
# Preparations
# --------------------------------------------------------------------------
class TestPreparations:
    def test_a_lead_time_and_a_start_date_work_out_the_due_date(
        self, client: TestClient, keeper: User
    ) -> None:
        activity = add_activity(client, starts_on="2019-06-01")
        response = client.post(
            f"/api/v1/activities/{activity['id']}/preparations",
            json={"description": "Book the vehicles", "lead_time_days": 30},
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 201, response.text
        assert response.json()["due_on"] == "2019-05-02"

    def test_ticking_it_off_records_the_day_and_untickings_clears_it(
        self, client: TestClient, keeper: User
    ) -> None:
        activity = add_activity(client)
        step = client.post(
            f"/api/v1/activities/{activity['id']}/preparations",
            json={"description": "Renew the insurance"},
            headers=auth_headers(client, "keeper"),
        ).json()

        done = client.patch(
            f"/api/v1/activities/{activity['id']}/preparations/{step['id']}",
            json={"is_done": True},
            headers=auth_headers(client, "keeper"),
        ).json()
        assert done["done_on"] == date.today().isoformat()

        reopened = client.patch(
            f"/api/v1/activities/{activity['id']}/preparations/{step['id']}",
            json={"is_done": False},
            headers=auth_headers(client, "keeper"),
        ).json()
        # A reopened step must not still claim to have been finished.
        assert reopened["done_on"] is None

    def test_a_finished_step_is_not_outstanding(self, client: TestClient, keeper: User) -> None:
        activity = add_activity(client)
        step = client.post(
            f"/api/v1/activities/{activity['id']}/preparations",
            json={"description": "Order the finds bags"},
            headers=auth_headers(client, "keeper"),
        ).json()
        client.patch(
            f"/api/v1/activities/{activity['id']}/preparations/{step['id']}",
            json={"is_done": True},
            headers=auth_headers(client, "keeper"),
        )

        body = client.get(
            f"/api/v1/activities/{activity['id']}", headers=auth_headers(client, "keeper")
        ).json()
        assert body["outstanding"]["preparations"] == []
        assert body["outstanding"]["is_clear"] is True


# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------
class TestCosts:
    def test_a_line_multiplies_out(self, client: TestClient, keeper: User) -> None:
        activity = add_activity(client)
        response = client.post(
            f"/api/v1/activities/{activity['id']}/costs",
            json={
                "description": "Vehicle hire",
                "unit_cost": 40,
                "quantity": 9,
                "unit": "day",
                "currency": "USD",
            },
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 201, response.text
        assert response.json()["total"] == 360.0

    def test_currencies_are_never_added_together(self, client: TestClient, keeper: User) -> None:
        activity = add_activity(client)
        for amount, currency in ((100, "USD"), (200, "JOD")):
            client.post(
                f"/api/v1/activities/{activity['id']}/costs",
                json={
                    "description": f"Something in {currency}",
                    "unit_cost": amount,
                    "currency": currency,
                },
                headers=auth_headers(client, "keeper"),
            )

        body = client.get(
            f"/api/v1/activities/{activity['id']}", headers=auth_headers(client, "keeper")
        ).json()
        totals = {line["currency"]: line["amount"] for line in body["cost_summary"]["by_currency"]}
        # Adding a dinar to a dollar produces a number that is wrong in a way
        # nobody notices until a funder does.
        assert totals == {"USD": 100.0, "JOD": 200.0}

    def test_the_estimated_part_of_a_total_stays_separable(
        self, client: TestClient, keeper: User
    ) -> None:
        activity = add_activity(client)
        client.post(
            f"/api/v1/activities/{activity['id']}/costs",
            json={"description": "Invoiced", "unit_cost": 300, "currency": "USD"},
            headers=auth_headers(client, "keeper"),
        )
        client.post(
            f"/api/v1/activities/{activity['id']}/costs",
            json={
                "description": "Remembered",
                "unit_cost": 200,
                "currency": "USD",
                "is_estimate": True,
            },
            headers=auth_headers(client, "keeper"),
        )

        body = client.get(
            f"/api/v1/activities/{activity['id']}", headers=auth_headers(client, "keeper")
        ).json()
        summary = body["cost_summary"]
        line = summary["by_currency"][0]
        assert line["amount"] == 500.0
        # A total built partly from recollection must never be presented as if
        # it were accounts.
        assert line["estimated_amount"] == 200.0
        assert summary["any_estimates"] is True
        assert summary["estimate_count"] == 1

    def test_a_permit_fee_counts_towards_the_total(self, client: TestClient, keeper: User) -> None:
        activity = add_activity(client)
        client.post(
            f"/api/v1/activities/{activity['id']}/costs",
            json={"description": "Vehicle hire", "unit_cost": 360, "currency": "USD"},
            headers=auth_headers(client, "keeper"),
        )
        client.post(
            f"/api/v1/activities/{activity['id']}/permits",
            json={"name": "Excavation licence", "cost": 150, "currency": "USD"},
            headers=auth_headers(client, "keeper"),
        )

        body = client.get(
            f"/api/v1/activities/{activity['id']}", headers=auth_headers(client, "keeper")
        ).json()
        # A costing that quietly omits the permit fee is the costing that comes
        # up short on the day.
        assert body["cost_summary"]["by_currency"][0]["amount"] == 510.0

    def test_a_free_line_is_refused(self, client: TestClient, keeper: User) -> None:
        activity = add_activity(client)
        response = client.post(
            f"/api/v1/activities/{activity['id']}/costs",
            json={"description": "Nothing at all", "unit_cost": 10, "quantity": 0},
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 422


# --------------------------------------------------------------------------
# The repeat — the module's whole purpose
# --------------------------------------------------------------------------
class TestRepeat:
    @pytest.fixture
    def last_season(self, client: TestClient, keeper: User) -> dict:
        activity = add_activity(
            client, title="North trench", starts_on="2019-06-01", ends_on="2019-06-12"
        )
        headers = auth_headers(client, "keeper")
        client.post(
            f"/api/v1/activities/{activity['id']}/equipment",
            json={
                "label": "Generator",
                "quantity": 1,
                "performance_notes": "Underpowered after 14:00",
            },
            headers=headers,
        )
        client.post(
            f"/api/v1/activities/{activity['id']}/permits",
            json={
                "name": "Excavation licence",
                "issuer": "Department of Antiquities",
                "reference": "DoA/2019/114",
                "status": "granted",
                "applied_on": "2019-02-01",
                "granted_on": "2019-03-19",
                "expires_on": "2019-12-31",
            },
            headers=headers,
        )
        client.post(
            f"/api/v1/activities/{activity['id']}/permits",
            json={"name": "Import licence for the scanner", "status": "not_required"},
            headers=headers,
        )
        step = client.post(
            f"/api/v1/activities/{activity['id']}/preparations",
            json={"description": "Book the vehicles", "lead_time_days": 30},
            headers=headers,
        ).json()
        client.patch(
            f"/api/v1/activities/{activity['id']}/preparations/{step['id']}",
            json={"is_done": True},
            headers=headers,
        )
        client.post(
            f"/api/v1/activities/{activity['id']}/costs",
            json={"description": "Vehicle hire", "unit_cost": 40, "quantity": 9, "unit": "day"},
            headers=headers,
        )
        client.patch(
            f"/api/v1/activities/{activity['id']}",
            json={"status": "completed", "outcome": "Two structures", "lessons": "Start earlier"},
            headers=headers,
        )
        return client.get(f"/api/v1/activities/{activity['id']}", headers=headers).json()

    def repeat(self, client: TestClient, source: dict, **fields) -> dict:
        response = client.post(
            f"/api/v1/activities/{source['id']}/repeat",
            json={"starts_on": "2020-06-01"} | fields,
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 201, response.text
        return response.json()

    def test_it_keeps_the_length_of_the_original(
        self, client: TestClient, keeper: User, last_season: dict
    ) -> None:
        fresh = self.repeat(client, last_season)
        # Twelve days last time, twelve days this time, without anybody having
        # to work out the end date.
        assert fresh["starts_on"] == "2020-06-01"
        assert fresh["ends_on"] == "2020-06-12"
        assert fresh["duration_days"] == 12

    def test_it_starts_as_planned_and_links_back(
        self, client: TestClient, keeper: User, last_season: dict
    ) -> None:
        fresh = self.repeat(client, last_season)
        assert fresh["status"] == "planned"
        assert fresh["repeated_from_id"] == last_season["id"]
        assert fresh["repeated_from_title"] == "North trench"

        original = client.get(
            f"/api/v1/activities/{last_season['id']}", headers=auth_headers(client, "keeper")
        ).json()
        assert original["repeat_count"] == 1

    def test_the_permit_comes_across_needing_reapplication(
        self, client: TestClient, keeper: User, last_season: dict
    ) -> None:
        fresh = self.repeat(client, last_season)
        licence = next(p for p in fresh["permits"] if p["name"] == "Excavation licence")

        # Turning up on site with last year's paperwork is the failure this
        # prevents.
        assert licence["status"] == "to_apply"
        assert licence["granted_on"] is None
        assert licence["applied_on"] is None
        assert licence["expires_on"] is None
        assert licence["reference"] is None
        # …but it remembers how long it took, which is the reason to look.
        assert licence["lead_time_days"] == 46

    def test_a_permit_that_was_not_required_stays_not_required(
        self, client: TestClient, keeper: User, last_season: dict
    ) -> None:
        fresh = self.repeat(client, last_season)
        scanner = next(p for p in fresh["permits"] if p["name"].startswith("Import licence"))
        # "We checked, and we did not need one" is a fact, not a to-do.
        assert scanner["status"] == "not_required"

    def test_preparations_come_across_unticked_with_new_due_dates(
        self, client: TestClient, keeper: User, last_season: dict
    ) -> None:
        fresh = self.repeat(client, last_season)
        step = fresh["preparations"][0]
        assert step["is_done"] is False
        assert step["done_on"] is None
        assert step["lead_time_days"] == 30
        # Thirty days before the *new* start date.
        assert step["due_on"] == "2020-05-02"

    def test_equipment_comes_across_with_its_performance_notes(
        self, client: TestClient, keeper: User, last_season: dict
    ) -> None:
        fresh = self.repeat(client, last_season)
        item = fresh["equipment"][0]
        assert item["label"] == "Generator"
        # Knowing the generator gave up at two o'clock is exactly the reason to
        # look at last year before ordering this year's.
        assert item["performance_notes"] == "Underpowered after 14:00"

    def test_costs_come_across_as_estimates(
        self, client: TestClient, keeper: User, last_season: dict
    ) -> None:
        fresh = self.repeat(client, last_season)
        line = fresh["costs"][0]
        assert line["description"] == "Vehicle hire"
        assert line["total"] == 360.0
        # Last year's price is an estimate of this year's, and calling it
        # anything else is how a budget goes wrong.
        assert line["is_estimate"] is True
        assert fresh["cost_summary"]["any_estimates"] is True

    def test_costs_can_be_left_behind(
        self, client: TestClient, keeper: User, last_season: dict
    ) -> None:
        fresh = self.repeat(client, last_season, copy_costs=False)
        assert fresh["costs"] == []

    def test_the_outcome_does_not_come_across(
        self, client: TestClient, keeper: User, last_season: dict
    ) -> None:
        fresh = self.repeat(client, last_season)
        # Nothing has happened yet. The lessons are still one click away
        # through the link back.
        assert fresh["outcome"] is None
        assert fresh["lessons"] is None


# --------------------------------------------------------------------------
# The brief
# --------------------------------------------------------------------------
class TestBrief:
    @pytest.fixture
    def furnished(self, client: TestClient, keeper: User) -> dict:
        activity = add_activity(
            client,
            title="North trench",
            starts_on="2019-06-01",
            ends_on="2019-06-12",
            location="Wadi Rum",
        )
        headers = auth_headers(client, "keeper")
        client.post(
            f"/api/v1/activities/{activity['id']}/equipment",
            json={"label": "Total station", "quantity": 1},
            headers=headers,
        )
        client.post(
            f"/api/v1/activities/{activity['id']}/permits",
            json={
                "name": "Excavation licence",
                "issuer": "Department of Antiquities",
                "status": "granted",
                "applied_on": "2019-02-01",
                "granted_on": "2019-03-19",
            },
            headers=headers,
        )
        client.post(
            f"/api/v1/activities/{activity['id']}/costs",
            json={"description": "Vehicle hire", "unit_cost": 40, "quantity": 9, "unit": "day"},
            headers=headers,
        )
        return activity

    def test_the_brief_is_plain_text_and_holds_the_logistics(
        self, client: TestClient, keeper: User, furnished: dict
    ) -> None:
        response = client.get(
            f"/api/v1/activities/{furnished['id']}/brief.txt",
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/plain")
        assert "attachment" in response.headers["content-disposition"]

        text = response.text
        assert "North trench" in text
        assert "Total station" in text
        assert "Excavation licence" in text
        assert "took 46 days" in text
        assert "Vehicle hire" in text
        assert "360.00 USD" in text

    def test_quantities_do_not_read_like_a_machine_wrote_them(
        self, client: TestClient, keeper: User, furnished: dict
    ) -> None:
        text = client.get(
            f"/api/v1/activities/{furnished['id']}/brief.txt",
            headers=auth_headers(client, "keeper"),
        ).text
        # A Decimal(12, 3) formatted naively gives "1.000 x Total station".
        assert "1 x Total station" in text
        assert "1.000" not in text

    def test_a_filename_with_a_slash_in_it_does_not_break_the_header(
        self, client: TestClient, keeper: User
    ) -> None:
        activity = add_activity(client, title="Survey 2019 / north")
        response = client.get(
            f"/api/v1/activities/{activity['id']}/brief.txt",
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 200
        disposition = response.headers["content-disposition"]
        assert "/" not in disposition.split("filename=")[1]

    def test_the_e_mail_endpoint_returns_the_brief_even_with_no_mail_server(
        self, client: TestClient, keeper: User, furnished: dict
    ) -> None:
        response = client.post(
            f"/api/v1/activities/{furnished['id']}/email",
            json={"to": ["director@example.org"], "message": "Can you sign off the hire?"},
            headers=auth_headers(client, "keeper"),
        )
        # A dig house with no outbound mail is a supported way to run this. The
        # request must not fail, and somebody must be left with something to
        # copy by hand.
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["sent"] is False
        assert "North trench" in body["brief"]
        assert body["detail"]


# --------------------------------------------------------------------------
# The hub's front page and the dropdown
# --------------------------------------------------------------------------
class TestHub:
    def test_the_summary_counts_by_kind_and_separates_past_from_future(
        self, client: TestClient, keeper: User
    ) -> None:
        add_activity(
            client,
            title="Old one",
            kind="survey",
            starts_on=(date.today() - timedelta(days=400)).isoformat(),
        )
        add_activity(
            client,
            title="Next one",
            kind="excavation",
            starts_on=(date.today() + timedelta(days=60)).isoformat(),
        )

        body = client.get(
            "/api/v1/activities/summary", headers=auth_headers(client, "keeper")
        ).json()
        assert body["total"] == 2
        assert body["by_kind"] == {"survey": 1, "excavation": 1}
        assert [item["title"] for item in body["upcoming"]] == ["Next one"]
        assert [item["title"] for item in body["recent"]] == ["Old one"]

    def test_a_finished_season_with_an_unfinished_checklist_is_not_flagged(
        self, client: TestClient, keeper: User
    ) -> None:
        activity = add_activity(
            client,
            title="Done years ago",
            starts_on=(date.today() - timedelta(days=400)).isoformat(),
        )
        client.post(
            f"/api/v1/activities/{activity['id']}/preparations",
            json={"description": "Never got round to it"},
            headers=auth_headers(client, "keeper"),
        )
        client.patch(
            f"/api/v1/activities/{activity['id']}",
            json={"status": "completed"},
            headers=auth_headers(client, "keeper"),
        )

        body = client.get(
            "/api/v1/activities/summary", headers=auth_headers(client, "keeper")
        ).json()
        # An unfinished checklist on a season three years past is history, not
        # a task. Flagging it trains people to ignore the flag.
        assert body["needing_attention"] == []

    def test_the_dropdown_is_open_to_anyone_signed_in(
        self, client: TestClient, keeper: User, outsider: User
    ) -> None:
        add_activity(client, title="North trench", starts_on="2019-06-01", location="Wadi Rum")

        response = client.get(
            "/api/v1/activities/options", headers=auth_headers(client, "outsider")
        )
        assert response.status_code == 200, response.text
        options = response.json()
        assert len(options) == 1
        assert "North trench" in options[0]["label"]
        assert "2019-06-01" in options[0]["label"]
        # Deliberately thin: choosing a name from a list must not hand over
        # what the season cost.
        assert "cost_summary" not in options[0]

    def test_the_dropdown_needs_a_signed_in_account(self, client: TestClient) -> None:
        assert client.get("/api/v1/activities/options").status_code == 401


# --------------------------------------------------------------------------
# The calendar, which is the part everybody shares
# --------------------------------------------------------------------------
class TestCalendar:
    def when(self, days: int = 7) -> str:
        return (datetime.now(UTC) + timedelta(days=days)).isoformat()

    def test_anybody_signed_in_may_add_a_day(self, client: TestClient, outsider: User) -> None:
        # No management access, no activities access, nothing. This is the
        # point of the change: the shared diary is kept by everybody.
        response = client.post(
            "/api/v1/management/events",
            json={"title": "Ahmed's last shift", "starts_at": self.when()},
            headers=auth_headers(client, "outsider"),
        )
        assert response.status_code == 201, response.text
        assert response.json()["can_edit"] is True

    def test_the_calendar_is_readable_by_anybody_signed_in(
        self, client: TestClient, keeper: User, outsider: User
    ) -> None:
        client.post(
            "/api/v1/management/events",
            json={"title": "Field season", "starts_at": self.when()},
            headers=auth_headers(client, "keeper"),
        )
        response = client.get("/api/v1/management/events", headers=auth_headers(client, "outsider"))
        assert response.status_code == 200
        assert response.json()["total"] == 1
        # Readable, but plainly not theirs to move.
        assert response.json()["items"][0]["can_edit"] is False

    def test_the_calendar_still_needs_an_account(self, client: TestClient) -> None:
        assert client.get("/api/v1/management/events").status_code == 401

    def test_nobody_quietly_rewrites_somebody_elses_day(
        self, client: TestClient, keeper: User, outsider: User
    ) -> None:
        event = client.post(
            "/api/v1/management/events",
            json={"title": "Field season", "starts_at": self.when()},
            headers=auth_headers(client, "keeper"),
        ).json()

        response = client.patch(
            f"/api/v1/management/events/{event['id']}",
            json={"title": "Cancelled"},
            headers=auth_headers(client, "outsider"),
        )
        assert response.status_code == 403
        assert (
            client.delete(
                f"/api/v1/management/events/{event['id']}",
                headers=auth_headers(client, "outsider"),
            ).status_code
            == 403
        )

    def test_your_own_day_is_yours_to_change(self, client: TestClient, outsider: User) -> None:
        event = client.post(
            "/api/v1/management/events",
            json={"title": "Mine", "starts_at": self.when()},
            headers=auth_headers(client, "outsider"),
        ).json()
        response = client.patch(
            f"/api/v1/management/events/{event['id']}",
            json={"title": "Mine, moved"},
            headers=auth_headers(client, "outsider"),
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Mine, moved"

    def test_a_supervisor_may_change_anybodys(
        self, client: TestClient, outsider: User, db: Session
    ) -> None:
        make_user(
            db,
            email="chief@example.org",
            username="chief",
            role=UserRole.VISITOR,
            modules={Module.MANAGEMENT: ModuleLevel.SUPERVISOR},
            grant_defaults=False,
        )
        event = client.post(
            "/api/v1/management/events",
            json={"title": "Somebody else's", "starts_at": self.when()},
            headers=auth_headers(client, "outsider"),
        ).json()
        response = client.patch(
            f"/api/v1/management/events/{event['id']}",
            json={"starts_at": self.when(14)},
            headers=auth_headers(client, "chief"),
        )
        assert response.status_code == 200


# --------------------------------------------------------------------------
# The calendar meeting the hub — the automatic workflow
# --------------------------------------------------------------------------
class TestCalendarFillsItselfIn:
    def when(self, days: int = 7) -> str:
        return (datetime.now(UTC) + timedelta(days=days)).isoformat()

    def test_picking_an_activity_fills_in_the_blanks(
        self, client: TestClient, keeper: User, outsider: User
    ) -> None:
        activity = add_activity(
            client, title="North trench", location="Wadi Rum", kind="excavation"
        )

        response = client.post(
            "/api/v1/management/events",
            json={"activity_id": activity["id"], "starts_at": self.when()},
            headers=auth_headers(client, "outsider"),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        # One choice, five fields. This is the whole of the "automatic
        # workflow" the calendar was asked for.
        assert body["title"] == "North trench"
        assert body["location"] == "Wadi Rum"
        assert body["kind"] == "excavation"
        assert body["activity_title"] == "North trench"
        assert body["activity_kind"] == "excavation"

    def test_what_somebody_typed_beats_what_the_activity_would_have_said(
        self, client: TestClient, keeper: User
    ) -> None:
        activity = add_activity(client, title="North trench", location="Wadi Rum")
        body = client.post(
            "/api/v1/management/events",
            json={
                "activity_id": activity["id"],
                "starts_at": self.when(),
                "title": "Site tour for the school",
                "location": "Meet at the gate",
            },
            headers=auth_headers(client, "keeper"),
        ).json()
        assert body["title"] == "Site tour for the school"
        assert body["location"] == "Meet at the gate"
        assert body["activity_title"] == "North trench"

    def test_an_event_with_neither_a_title_nor_an_activity_is_refused(
        self, client: TestClient, keeper: User
    ) -> None:
        response = client.post(
            "/api/v1/management/events",
            json={"starts_at": self.when()},
            headers=auth_headers(client, "keeper"),
        )
        # A coloured block attached to nothing is one nobody can interpret.
        assert response.status_code == 422

    def test_pointing_at_an_activity_that_does_not_exist_is_a_404(
        self, client: TestClient, keeper: User
    ) -> None:
        import uuid as _uuid

        response = client.post(
            "/api/v1/management/events",
            json={"activity_id": str(_uuid.uuid4()), "starts_at": self.when()},
            headers=auth_headers(client, "keeper"),
        )
        assert response.status_code == 404

    def test_the_calendar_can_be_filtered_to_one_activity(
        self, client: TestClient, keeper: User
    ) -> None:
        activity = add_activity(client, title="North trench")
        headers = auth_headers(client, "keeper")
        client.post(
            "/api/v1/management/events",
            json={"activity_id": activity["id"], "starts_at": self.when()},
            headers=headers,
        )
        client.post(
            "/api/v1/management/events",
            json={"title": "Unrelated", "starts_at": self.when(2)},
            headers=headers,
        )

        response = client.get(
            f"/api/v1/management/events?activity_id={activity['id']}", headers=headers
        )
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["title"] == "North trench"

    def test_attaching_an_existing_day_to_an_activity_keeps_its_own_title(
        self, client: TestClient, keeper: User
    ) -> None:
        activity = add_activity(client, title="North trench", location="Wadi Rum")
        headers = auth_headers(client, "keeper")
        event = client.post(
            "/api/v1/management/events",
            json={"title": "Ahmed's last shift", "starts_at": self.when()},
            headers=headers,
        ).json()

        body = client.patch(
            f"/api/v1/management/events/{event['id']}",
            json={"activity_id": activity["id"]},
            headers=headers,
        ).json()
        assert body["title"] == "Ahmed's last shift"
        # …but it gains the link, and what it did not say.
        assert body["activity_title"] == "North trench"
        assert body["location"] == "Wadi Rum"


# --------------------------------------------------------------------------
# Everyone gets the hub
# --------------------------------------------------------------------------
class TestAccessIsSeeded:
    def test_a_new_account_can_reach_the_hub_without_anybody_acting(
        self, client: TestClient, db: Session
    ) -> None:
        fresh = make_user(db, email="fresh@example.org", username="fresh", role=UserRole.STUDENT)
        # Seeded on creation, like archaeology. A shared record that half the
        # team has to ask for is a record one person ends up keeping.
        assert fresh.level_in(Module.ACTIVITIES) is ModuleLevel.CONTRIBUTOR
        assert fresh.level_in(Module.ARCHAEOLOGY) is ModuleLevel.CONTRIBUTOR
        # And not the closed ones.
        assert fresh.level_in(Module.MANAGEMENT) is None

    def test_an_administrator_needs_no_row(self, client: TestClient, admin: User) -> None:
        response = client.post(
            "/api/v1/activities",
            json={"title": "Administrators hold every module implicitly"},
            headers=auth_headers(client, "admin"),
        )
        assert response.status_code == 201
