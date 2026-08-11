"""Budgets, expenses, tasks and the calendar.

The money tests are the ones that matter. A grant report that is nearly right
is a grant report that gets somebody in trouble, and the specific way this can
go wrong — counting only what has been paid, and telling a project director
they have funds they have already committed — is invisible until the money
runs out.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Module, ModuleLevel, User, UserRole
from tests.conftest import auth_headers, make_user


@pytest.fixture
def treasurer(db: Session) -> User:
    """Runs the money. Senior in management, absent from everything else."""
    return make_user(
        db,
        email="treasurer@example.org",
        username="treasurer",
        role=UserRole.VISITOR,
        modules={Module.MANAGEMENT: ModuleLevel.SUPERVISOR},
        grant_defaults=False,
    )


@pytest.fixture
def assistant(db: Session) -> User:
    """May record spending, not delete it."""
    return make_user(
        db,
        email="assistant@example.org",
        username="assistant",
        role=UserRole.VISITOR,
        modules={Module.MANAGEMENT: ModuleLevel.CONTRIBUTOR},
        grant_defaults=False,
    )


@pytest.fixture
def digger(db: Session) -> User:
    """A field archaeologist with no business in the accounts."""
    return make_user(
        db,
        email="fielder@example.org",
        username="fielder",
        role=UserRole.RESEARCHER,
        grant_defaults=False,
    )


def add_budget(client: TestClient, *, who: str = "treasurer", **fields) -> dict:
    payload = {"code": "GR-2026", "name": "Survey grant", "amount": 10000} | fields
    response = client.post(
        "/api/v1/management/budgets", json=payload, headers=auth_headers(client, who)
    )
    assert response.status_code == 201, response.text
    return response.json()


def spend(client: TestClient, budget_id: str, *, who: str = "treasurer", **fields) -> dict:
    payload = {
        "description": "Something",
        "amount": 100,
        "spent_on": date.today().isoformat(),
    } | fields
    response = client.post(
        f"/api/v1/management/budgets/{budget_id}/expenses",
        json=payload,
        headers=auth_headers(client, who),
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestBudgets:
    def test_a_new_fund_has_all_of_it_available(self, client: TestClient, treasurer: User) -> None:
        budget = add_budget(client, amount=10000)

        assert budget["available"] == 10000
        assert budget["spent"] == 0
        assert budget["used_percent"] == 0

    def test_two_funds_cannot_share_a_code(self, client: TestClient, treasurer: User) -> None:
        add_budget(client, code="GR-1")

        response = client.post(
            "/api/v1/management/budgets",
            json={"code": "GR-1", "name": "Another", "amount": 5},
            headers=auth_headers(client, "treasurer"),
        )

        assert response.status_code == 409

    def test_the_accounts_are_closed_to_people_outside_them(
        self, client: TestClient, treasurer: User, digger: User
    ) -> None:
        """A field director needs no sight of what a conservator is paid."""
        add_budget(client)

        response = client.get("/api/v1/management/budgets", headers=auth_headers(client, "fielder"))

        assert response.json()["total"] == 0

    def test_a_fund_cannot_end_before_it_starts(self, client: TestClient, treasurer: User) -> None:
        response = client.post(
            "/api/v1/management/budgets",
            json={
                "code": "GR-X",
                "name": "Backwards",
                "amount": 100,
                "starts_on": "2026-06-01",
                "ends_on": "2026-01-01",
            },
            headers=auth_headers(client, "treasurer"),
        )

        assert response.status_code == 422


class TestTheBalance:
    """The arithmetic the whole module rests on."""

    def test_committed_money_is_gone_even_though_it_has_not_been_paid(
        self, client: TestClient, treasurer: User
    ) -> None:
        """The important one. Money promised to a supplier cannot be spent
        again — a balance counting only cleared invoices tells a project
        director they have funds they have already committed, which is how a
        grant gets overspent by people being careful with it."""
        budget = add_budget(client, amount=10000)
        spend(client, budget["id"], amount=3000, status="committed")

        after = client.get(
            f"/api/v1/management/budgets/{budget['id']}", headers=auth_headers(client, "treasurer")
        ).json()

        assert after["committed"] == 3000
        assert after["paid"] == 0
        assert after["available"] == 7000, "committed money must reduce what is available"

    def test_planned_spending_does_not_reduce_the_balance(
        self, client: TestClient, treasurer: User
    ) -> None:
        """A forecast that quietly reduces the balance turns "we might need a
        second total station" into "we cannot afford one"."""
        budget = add_budget(client, amount=10000)
        spend(client, budget["id"], amount=4000, status="planned")

        after = client.get(
            f"/api/v1/management/budgets/{budget['id']}", headers=auth_headers(client, "treasurer")
        ).json()

        assert after["planned"] == 4000
        assert after["available"] == 10000
        assert after["spent"] == 0

    def test_cancelled_spending_gives_the_money_back(
        self, client: TestClient, treasurer: User
    ) -> None:
        budget = add_budget(client, amount=10000)
        expense = spend(client, budget["id"], amount=2500, status="committed")
        headers = auth_headers(client, "treasurer")

        client.patch(
            f"/api/v1/management/expenses/{expense['id']}",
            json={"status": "cancelled"},
            headers=headers,
        )

        after = client.get(f"/api/v1/management/budgets/{budget['id']}", headers=headers).json()
        assert after["available"] == 10000

    def test_paid_and_committed_add_up_together(self, client: TestClient, treasurer: User) -> None:
        budget = add_budget(client, amount=10000)
        spend(client, budget["id"], amount=1500, status="paid", paid_on=date.today().isoformat())
        spend(client, budget["id"], amount=2500, status="committed")

        after = client.get(
            f"/api/v1/management/budgets/{budget['id']}", headers=auth_headers(client, "treasurer")
        ).json()

        assert after["paid"] == 1500
        assert after["committed"] == 2500
        assert after["spent"] == 4000
        assert after["available"] == 6000
        assert after["used_percent"] == 40.0

    def test_the_balance_cannot_be_typed_over(self, client: TestClient, treasurer: User) -> None:
        """If a PATCH could set it, the expenses behind it would be
        decorative."""
        budget = add_budget(client, amount=10000)
        spend(client, budget["id"], amount=3000)
        headers = auth_headers(client, "treasurer")

        client.patch(
            f"/api/v1/management/budgets/{budget['id']}",
            json={"available": 99999, "spent": 0},
            headers=headers,
        )

        after = client.get(f"/api/v1/management/budgets/{budget['id']}", headers=headers).json()
        assert after["available"] == 7000

    def test_a_budget_of_nothing_is_not_a_hundred_percent_used(
        self, client: TestClient, treasurer: User
    ) -> None:
        """Drawing a progress bar for it invents a fact."""
        budget = add_budget(client, code="GR-0", amount=0)

        assert budget["used_percent"] == 0
        assert budget["overspent"] is False


class TestOverspending:
    def test_going_over_is_recorded_and_reported_not_refused(
        self, client: TestClient, treasurer: User
    ) -> None:
        """A grant genuinely does get overspent. A platform that refuses to
        record what happened is one where the real figures live in a
        spreadsheet nobody else can see."""
        budget = add_budget(client, amount=1000)

        response = client.post(
            f"/api/v1/management/budgets/{budget['id']}/expenses",
            json={"description": "Emergency hire", "amount": 1500, "spent_on": "2026-06-01"},
            headers=auth_headers(client, "treasurer"),
        )

        assert response.status_code == 201, response.text
        assert response.json()["overspent_by"] == 500
        assert response.json()["budget_available_after"] == -500

    def test_spending_within_the_fund_reports_no_overspend(
        self, client: TestClient, treasurer: User
    ) -> None:
        budget = add_budget(client, amount=1000)

        result = spend(client, budget["id"], amount=400)

        assert result["overspent_by"] is None
        assert result["budget_available_after"] == 600

    def test_a_closed_fund_takes_no_more_spending(
        self, client: TestClient, treasurer: User
    ) -> None:
        """Closing is the alternative to deleting, so it has to actually
        stop things."""
        budget = add_budget(client, amount=1000)
        headers = auth_headers(client, "treasurer")
        client.patch(
            f"/api/v1/management/budgets/{budget['id']}", json={"status": "closed"}, headers=headers
        )

        response = client.post(
            f"/api/v1/management/budgets/{budget['id']}/expenses",
            json={"description": "Late invoice", "amount": 10, "spent_on": "2026-06-01"},
            headers=headers,
        )

        assert response.status_code == 409


class TestExpenses:
    def test_an_expense_cannot_be_zero_or_negative(
        self, client: TestClient, treasurer: User
    ) -> None:
        """A negative expense is a refund pretending to be spending, and it
        makes every category breakdown quietly wrong."""
        budget = add_budget(client)

        for amount in (0, -50):
            response = client.post(
                f"/api/v1/management/budgets/{budget['id']}/expenses",
                json={"description": "x", "amount": amount, "spent_on": "2026-06-01"},
                headers=auth_headers(client, "treasurer"),
            )
            assert response.status_code == 422, amount

    def test_it_cannot_be_paid_before_it_was_incurred(
        self, client: TestClient, treasurer: User
    ) -> None:
        budget = add_budget(client)

        response = client.post(
            f"/api/v1/management/budgets/{budget['id']}/expenses",
            json={
                "description": "Time travel",
                "amount": 10,
                "spent_on": "2026-06-01",
                "paid_on": "2026-05-01",
            },
            headers=auth_headers(client, "treasurer"),
        )

        assert response.status_code == 422

    def test_it_inherits_the_funds_currency(self, client: TestClient, treasurer: User) -> None:
        """Retyping the currency on every line is how half of them end up
        wrong."""
        budget = add_budget(client, code="GR-JOD", currency="JOD")

        expense = spend(client, budget["id"], amount=50)

        assert expense["currency"] == "JOD"

    def test_marking_it_paid_dates_it(self, client: TestClient, treasurer: User) -> None:
        """A paid line with no date cannot be reconciled against a
        statement."""
        budget = add_budget(client)
        expense = spend(client, budget["id"], status="committed")

        updated = client.patch(
            f"/api/v1/management/expenses/{expense['id']}",
            json={"status": "paid"},
            headers=auth_headers(client, "treasurer"),
        ).json()

        assert updated["paid_on"] == date.today().isoformat()

    def test_the_ledger_names_the_fund_each_line_is_against(
        self, client: TestClient, treasurer: User
    ) -> None:
        """Listed across every fund, "1,500" says nothing without it."""
        budget = add_budget(client, code="GR-7", name="Conservation fund")
        spend(client, budget["id"])

        listed = client.get(
            "/api/v1/management/expenses", headers=auth_headers(client, "treasurer")
        ).json()

        assert listed["items"][0]["budget_code"] == "GR-7"
        assert listed["items"][0]["budget_name"] == "Conservation fund"


class TestTheFundersReport:
    def test_spending_is_broken_down_by_category_largest_first(
        self, client: TestClient, treasurer: User
    ) -> None:
        """The one report every funder asks for."""
        budget = add_budget(client, amount=100000)
        spend(client, budget["id"], amount=5000, category="salaries")
        spend(client, budget["id"], amount=1200, category="travel")
        spend(client, budget["id"], amount=800, category="travel")
        spend(client, budget["id"], amount=300, category="consumables")

        detail = client.get(
            f"/api/v1/management/budgets/{budget['id']}", headers=auth_headers(client, "treasurer")
        ).json()

        lines = detail["by_category"]
        assert [line["category"] for line in lines] == ["salaries", "travel", "consumables"]
        assert lines[1]["amount"] == 2000
        assert lines[1]["count"] == 2
        assert lines[0]["percent"] == 68.5

    def test_categories_with_nothing_in_them_are_left_out(
        self, client: TestClient, treasurer: User
    ) -> None:
        """A report listing nine headings of zero to say something about one
        is a report nobody reads to the end."""
        budget = add_budget(client)
        spend(client, budget["id"], category="permits")

        detail = client.get(
            f"/api/v1/management/budgets/{budget['id']}", headers=auth_headers(client, "treasurer")
        ).json()

        assert len(detail["by_category"]) == 1

    def test_planned_spending_is_not_in_the_breakdown(
        self, client: TestClient, treasurer: User
    ) -> None:
        """A funder asking what their money went on does not want a
        forecast in the answer."""
        budget = add_budget(client)
        spend(client, budget["id"], amount=100, category="travel", status="paid")
        spend(client, budget["id"], amount=9000, category="salaries", status="planned")

        detail = client.get(
            f"/api/v1/management/budgets/{budget['id']}", headers=auth_headers(client, "treasurer")
        ).json()

        assert [line["category"] for line in detail["by_category"]] == ["travel"]

    def test_the_totals_are_kept_per_currency(self, client: TestClient, treasurer: User) -> None:
        """Adding a dinar to a dollar produces a number that is wrong in a
        way nobody notices until a funder does."""
        add_budget(client, code="GR-USD", amount=10000, currency="USD")
        add_budget(client, code="GR-JOD", amount=7000, currency="JOD")

        totals = client.get(
            "/api/v1/management/budgets/totals", headers=auth_headers(client, "treasurer")
        ).json()

        assert totals["by_currency"] == {"USD": 10000, "JOD": 7000}
        assert totals["budget_count"] == 2

    def test_a_fund_that_expired_with_money_left_is_flagged(
        self, client: TestClient, treasurer: User
    ) -> None:
        """Unspent grant money usually has to be returned, and nobody finds
        out by accident in time."""
        budget = add_budget(
            client,
            amount=5000,
            starts_on=(date.today() - timedelta(days=400)).isoformat(),
            ends_on=(date.today() - timedelta(days=30)).isoformat(),
        )

        detail = client.get(
            f"/api/v1/management/budgets/{budget['id']}", headers=auth_headers(client, "treasurer")
        ).json()
        totals = client.get(
            "/api/v1/management/budgets/totals", headers=auth_headers(client, "treasurer")
        ).json()

        assert detail["expired_with_funds"] is True
        assert budget["id"] in totals["needing_attention"]


class TestDeleting:
    def test_a_fund_with_spending_against_it_cannot_be_deleted(
        self, client: TestClient, treasurer: User
    ) -> None:
        """It is a financial record somebody may have to answer for years
        later."""
        budget = add_budget(client)
        spend(client, budget["id"])

        response = client.delete(
            f"/api/v1/management/budgets/{budget['id']}", headers=auth_headers(client, "treasurer")
        )

        assert response.status_code == 409
        assert "Close it instead" in response.json()["detail"]

    def test_an_empty_fund_can_be(self, client: TestClient, treasurer: User) -> None:
        budget = add_budget(client)

        response = client.delete(
            f"/api/v1/management/budgets/{budget['id']}", headers=auth_headers(client, "treasurer")
        )

        assert response.status_code == 200

    def test_a_contributor_may_spend_but_not_delete(
        self, client: TestClient, treasurer: User, assistant: User
    ) -> None:
        budget = add_budget(client)

        spent = client.post(
            f"/api/v1/management/budgets/{budget['id']}/expenses",
            json={"description": "Petrol", "amount": 40, "spent_on": "2026-06-01"},
            headers=auth_headers(client, "assistant"),
        )
        deleted = client.delete(
            f"/api/v1/management/budgets/{budget['id']}",
            headers=auth_headers(client, "assistant"),
        )

        assert spent.status_code == 201
        assert deleted.status_code == 403


class TestTasks:
    def test_a_new_task_goes_to_the_top(self, client: TestClient, treasurer: User) -> None:
        """A task somebody just typed is the one they are thinking about."""
        headers = auth_headers(client, "treasurer")
        for title in ("First", "Second", "Third"):
            client.post("/api/v1/management/tasks", json={"title": title}, headers=headers)

        listed = client.get("/api/v1/management/tasks", headers=headers).json()

        assert [row["title"] for row in listed["items"]] == ["Third", "Second", "First"]

    def test_finishing_one_dates_it(self, client: TestClient, treasurer: User) -> None:
        headers = auth_headers(client, "treasurer")
        task = client.post(
            "/api/v1/management/tasks", json={"title": "Wash the pottery"}, headers=headers
        ).json()

        done = client.patch(
            f"/api/v1/management/tasks/{task['id']}", json={"status": "done"}, headers=headers
        ).json()

        assert done["completed_at"] is not None

    def test_reopening_one_clears_the_date(self, client: TestClient, treasurer: User) -> None:
        """A reopened task claiming a completion date is a task the report
        counts as finished."""
        headers = auth_headers(client, "treasurer")
        task = client.post(
            "/api/v1/management/tasks", json={"title": "Draw section"}, headers=headers
        ).json()
        client.patch(
            f"/api/v1/management/tasks/{task['id']}", json={"status": "done"}, headers=headers
        )

        reopened = client.patch(
            f"/api/v1/management/tasks/{task['id']}", json={"status": "todo"}, headers=headers
        ).json()

        assert reopened["completed_at"] is None

    def test_an_overdue_task_counts_the_days(self, client: TestClient, treasurer: User) -> None:
        headers = auth_headers(client, "treasurer")
        client.post(
            "/api/v1/management/tasks",
            json={"title": "Late", "due_on": (date.today() - timedelta(days=5)).isoformat()},
            headers=headers,
        )

        listed = client.get("/api/v1/management/tasks?overdue=true", headers=headers).json()

        assert listed["total"] == 1
        assert listed["items"][0]["days_overdue"] == 5

    def test_a_finished_task_is_never_overdue(self, client: TestClient, treasurer: User) -> None:
        """Something handed in late is still handed in."""
        headers = auth_headers(client, "treasurer")
        task = client.post(
            "/api/v1/management/tasks",
            json={
                "title": "Late but done",
                "due_on": (date.today() - timedelta(days=5)).isoformat(),
            },
            headers=headers,
        ).json()
        client.patch(
            f"/api/v1/management/tasks/{task['id']}", json={"status": "done"}, headers=headers
        )

        listed = client.get("/api/v1/management/tasks?overdue=true", headers=headers).json()
        board = client.get("/api/v1/management/tasks/board", headers=headers).json()

        assert listed["total"] == 0
        assert board["overdue_count"] == 0

    def test_the_board_groups_by_status_and_leaves_cancelled_off(
        self, client: TestClient, treasurer: User
    ) -> None:
        """A board that shows cancelled work is a board with a growing pile
        of things nobody is going to do."""
        headers = auth_headers(client, "treasurer")
        for title, state in [("A", "todo"), ("B", "in_progress"), ("C", "cancelled")]:
            task = client.post(
                "/api/v1/management/tasks", json={"title": title}, headers=headers
            ).json()
            if state != "todo":
                client.patch(
                    f"/api/v1/management/tasks/{task['id']}",
                    json={"status": state},
                    headers=headers,
                )

        board = client.get("/api/v1/management/tasks/board", headers=headers).json()

        assert [row["title"] for row in board["todo"]] == ["A"]
        assert [row["title"] for row in board["in_progress"]] == ["B"]
        everything = board["todo"] + board["in_progress"] + board["blocked"] + board["done"]
        assert "C" not in [row["title"] for row in everything]

    def test_the_board_is_not_read_as_a_task_id(self, client: TestClient, treasurer: User) -> None:
        response = client.get(
            "/api/v1/management/tasks/board", headers=auth_headers(client, "treasurer")
        )

        assert response.status_code == 200

    def test_work_can_be_given_to_somebody_with_no_account(
        self, client: TestClient, treasurer: User
    ) -> None:
        """A task list that can only name staff is a list with holes in it."""
        response = client.post(
            "/api/v1/management/tasks",
            json={"title": "Sort the flint", "assignee_label": "Nour, volunteer"},
            headers=auth_headers(client, "treasurer"),
        )

        assert response.status_code == 201
        assert response.json()["assignee_label"] == "Nour, volunteer"

    def test_an_assignee_with_an_account_gets_their_name_filled_in(
        self, client: TestClient, treasurer: User, assistant: User
    ) -> None:
        response = client.post(
            "/api/v1/management/tasks",
            json={"title": "Reconcile receipts", "assignee_id": str(assistant.id)},
            headers=auth_headers(client, "treasurer"),
        )

        assert response.json()["assignee_label"] == assistant.full_name


class TestCalendar:
    def test_an_event_spanning_the_window_is_shown(
        self, client: TestClient, treasurer: User
    ) -> None:
        """A field season running June to August is happening in July, and a
        calendar that hides it when you look at July is one people stop
        trusting."""
        headers = auth_headers(client, "treasurer")
        client.post(
            "/api/v1/management/events",
            json={
                "title": "Field season",
                "kind": "field season",
                "starts_at": "2026-06-01T00:00:00Z",
                "ends_at": "2026-08-31T00:00:00Z",
                "all_day": True,
            },
            headers=headers,
        )

        july = client.get(
            "/api/v1/management/events?since=2026-07-01T00:00:00Z&until=2026-07-31T00:00:00Z",
            headers=headers,
        ).json()

        assert july["total"] == 1

    def test_an_event_cannot_end_before_it_begins(
        self, client: TestClient, treasurer: User
    ) -> None:
        response = client.post(
            "/api/v1/management/events",
            json={
                "title": "Backwards",
                "starts_at": "2026-06-10T09:00:00Z",
                "ends_at": "2026-06-01T09:00:00Z",
            },
            headers=auth_headers(client, "treasurer"),
        )

        assert response.status_code == 422

    def test_it_cannot_be_edited_into_ending_before_it_begins_either(
        self, client: TestClient, treasurer: User
    ) -> None:
        headers = auth_headers(client, "treasurer")
        event = client.post(
            "/api/v1/management/events",
            json={
                "title": "Study visit",
                "starts_at": "2026-06-01T09:00:00Z",
                "ends_at": "2026-06-10T17:00:00Z",
            },
            headers=headers,
        ).json()

        response = client.patch(
            f"/api/v1/management/events/{event['id']}",
            json={"ends_at": "2026-05-01T09:00:00Z"},
            headers=headers,
        )

        assert response.status_code == 422

    def test_a_deadline_with_no_end_still_appears(
        self, client: TestClient, treasurer: User
    ) -> None:
        headers = auth_headers(client, "treasurer")
        when = datetime.now(UTC) + timedelta(days=10)
        client.post(
            "/api/v1/management/events",
            json={"title": "Report due", "kind": "deadline", "starts_at": when.isoformat()},
            headers=headers,
        )

        # `params=` rather than an f-string: the "+00:00" offset contains a
        # plus, which means a space in a query string unless it is encoded.
        window = client.get(
            "/api/v1/management/events",
            params={
                "since": datetime.now(UTC).isoformat(),
                "until": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            },
            headers=headers,
        ).json()

        assert window["total"] == 1


# --------------------------------------------------------------------------
# Work assigned to a person
# --------------------------------------------------------------------------
class TestAssignedWork:
    """A task given to somebody they cannot see is a task that will not happen.

    The management module is closed by default, and rightly — but the closure
    has to stop at the assignee's own list, or assigning work to a field
    archaeologist is a private note the manager makes to themselves.
    """

    def add_task(self, client: TestClient, *, who: str = "treasurer", **fields) -> dict:
        payload = {"title": "Photograph the 2024 sherds"} | fields
        response = client.post(
            "/api/v1/management/tasks", json=payload, headers=auth_headers(client, who)
        )
        assert response.status_code == 201, response.text
        return response.json()

    def test_an_assignee_with_no_management_access_can_read_their_own_list(
        self, client: TestClient, treasurer: User, digger: User
    ) -> None:
        self.add_task(client, assignee_id=str(digger.id))

        response = client.get(
            "/api/v1/management/tasks/mine", headers=auth_headers(client, "fielder")
        )
        assert response.status_code == 200, response.text
        assert [item["title"] for item in response.json()["items"]] == [
            "Photograph the 2024 sherds"
        ]

    def test_the_same_person_still_cannot_read_the_whole_board(
        self, client: TestClient, treasurer: User, digger: User
    ) -> None:
        self.add_task(client, assignee_id=str(digger.id))
        # Their own work, yes. Everybody's work and the accounts beside it, no.
        assert (
            client.get(
                "/api/v1/management/tasks", headers=auth_headers(client, "fielder")
            ).status_code
            == 403
        )

    def test_it_shows_only_your_own(
        self, client: TestClient, treasurer: User, digger: User, assistant: User
    ) -> None:
        self.add_task(client, title="Theirs", assignee_id=str(digger.id))
        self.add_task(client, title="Somebody else's", assignee_id=str(assistant.id))
        self.add_task(client, title="Nobody's")

        titles = [
            item["title"]
            for item in client.get(
                "/api/v1/management/tasks/mine", headers=auth_headers(client, "fielder")
            ).json()["items"]
        ]
        assert titles == ["Theirs"]

    def test_finished_work_is_out_of_the_way_unless_asked_for(
        self, client: TestClient, treasurer: User, digger: User
    ) -> None:
        task = self.add_task(client, assignee_id=str(digger.id))
        client.patch(
            f"/api/v1/management/tasks/{task['id']}",
            json={"status": "done"},
            headers=auth_headers(client, "treasurer"),
        )

        headers = auth_headers(client, "fielder")
        assert client.get("/api/v1/management/tasks/mine", headers=headers).json()["total"] == 0
        with_done = client.get("/api/v1/management/tasks/mine?include_done=true", headers=headers)
        assert with_done.json()["total"] == 1

    def test_being_given_a_task_notifies_you(
        self, client: TestClient, treasurer: User, digger: User
    ) -> None:
        self.add_task(client, assignee_id=str(digger.id), due_on="2026-09-01")

        response = client.get("/api/v1/notifications", headers=auth_headers(client, "fielder"))
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 1
        assert "given a task" in items[0]["title"]
        # The date is in the body, because "when" is the first thing anybody
        # asks about work that has just appeared.
        assert "2026-09-01" in (items[0]["body"] or "")

    def test_editing_the_date_does_not_claim_to_reassign_it(
        self, client: TestClient, treasurer: User, digger: User
    ) -> None:
        task = self.add_task(client, assignee_id=str(digger.id))
        client.patch(
            f"/api/v1/management/tasks/{task['id']}",
            json={"due_on": "2026-10-01"},
            headers=auth_headers(client, "treasurer"),
        )

        items = client.get("/api/v1/notifications", headers=auth_headers(client, "fielder")).json()[
            "items"
        ]
        # One for the assignment, and nothing for the date change. A list that
        # pings on every edit is a list people mute.
        assert len(items) == 1

    def test_reassigning_tells_the_new_person(
        self, client: TestClient, treasurer: User, digger: User, assistant: User
    ) -> None:
        task = self.add_task(client, assignee_id=str(assistant.id))
        client.patch(
            f"/api/v1/management/tasks/{task['id']}",
            json={"assignee_id": str(digger.id)},
            headers=auth_headers(client, "treasurer"),
        )

        items = client.get("/api/v1/notifications", headers=auth_headers(client, "fielder")).json()[
            "items"
        ]
        assert len(items) == 1
        assert "reassigned" in items[0]["title"]

    def test_your_own_list_needs_an_account(self, client: TestClient) -> None:
        assert client.get("/api/v1/management/tasks/mine").status_code == 401
