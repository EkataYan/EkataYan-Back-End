from decimal import Decimal
from flask import Blueprint, g
from app.middleware.auth_middleware import authenticated, require_trip
from app.repositories import ExpenseRepository
from app.utils.responses import APIError, success
from app.utils.validators import EqualExpenseInput, SettlementInput, identifier, parse

bp = Blueprint("expenses", __name__)


@bp.post("/trips/<trip_id>/expenses")
@authenticated
def create(trip_id):
    trip_id = identifier(trip_id)
    data = parse(EqualExpenseInput, error_status=400).model_dump(mode="json")
    require_trip(trip_id)
    return success(ExpenseRepository(g.db).create_equal(trip_id, data), 201)


@bp.get("/trips/<trip_id>/expenses")
@authenticated
def list_expenses(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id)
    return success(ExpenseRepository(g.db).public_list(trip_id))


@bp.get("/trips/<trip_id>/expense-balances")
@authenticated
def balances(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id)
    result = ExpenseRepository(g.db).balances(trip_id)
    if isinstance(result, dict):
        result["debts"] = simplify_debts(result.get("balances", []))
    return success(result)


def simplify_debts(balances):
    """Return a stable minimum-transfer plan from authoritative net balances."""
    debtors = sorted(
        [[row, -Decimal(str(row.get("net_balance", "0")))] for row in balances
         if Decimal(str(row.get("net_balance", "0"))) < 0],
        key=lambda item: item[0].get("user_id", ""),
    )
    creditors = sorted(
        [[row, Decimal(str(row.get("net_balance", "0")))] for row in balances
         if Decimal(str(row.get("net_balance", "0"))) > 0],
        key=lambda item: item[0].get("user_id", ""),
    )
    result, debtor_index, creditor_index = [], 0, 0
    while debtor_index < len(debtors) and creditor_index < len(creditors):
        debtor, owed = debtors[debtor_index]
        creditor, due = creditors[creditor_index]
        amount = min(owed, due).quantize(Decimal("0.01"))
        if amount > 0:
            result.append({
                "paid_by": debtor["user_id"], "paid_to": creditor["user_id"],
                "amount": str(amount),
                "payer": {key: debtor.get(key) for key in ("user_id", "display_name", "username", "avatar_url")},
                "recipient": {key: creditor.get(key) for key in ("user_id", "display_name", "username", "avatar_url")},
            })
        debtors[debtor_index][1] -= amount
        creditors[creditor_index][1] -= amount
        if debtors[debtor_index][1] == 0:
            debtor_index += 1
        if creditors[creditor_index][1] == 0:
            creditor_index += 1
    return result


@bp.put("/trips/<trip_id>/expenses/<expense_id>")
@bp.patch("/trips/<trip_id>/expenses/<expense_id>")
@authenticated
def update(trip_id, expense_id):
    trip_id = identifier(trip_id)
    expense_id = identifier(expense_id)
    data = parse(EqualExpenseInput, error_status=400).model_dump(mode="json")
    expense = ExpenseRepository(g.db).get(expense_id)
    if expense["trip_id"] != trip_id:
        raise APIError("NOT_FOUND", "Expense not found for this trip.", 404)
    require_trip(trip_id, admin=expense["created_by"] != g.user_id)
    return success(ExpenseRepository(g.db).update_equal(trip_id, expense_id, data))


@bp.delete("/trips/<trip_id>/expenses/<expense_id>")
@authenticated
def delete(trip_id, expense_id):
    trip_id = identifier(trip_id)
    expense_id = identifier(expense_id)
    require_trip(trip_id, owner=True)
    expense = ExpenseRepository(g.db).get(expense_id)
    if expense["trip_id"] != trip_id:
        raise APIError("NOT_FOUND", "Expense not found for this trip.", 404)
    ExpenseRepository(g.db).delete(trip_id, expense_id)
    return success({"deleted": True})


@bp.delete("/expenses/<expense_id>")
@authenticated
def delete_legacy(expense_id):
    """Compatibility route; authorization remains owner-only and server-derived."""
    expense_id = identifier(expense_id)
    expense = ExpenseRepository(g.db).get(expense_id)
    trip_id = expense["trip_id"]
    require_trip(trip_id, owner=True)
    ExpenseRepository(g.db).delete(trip_id, expense_id)
    return success({"deleted": True})


@bp.get("/trips/<trip_id>/settlements")
@authenticated
def settlements(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id)
    return success(ExpenseRepository(g.db).settlements(trip_id))


@bp.post("/trips/<trip_id>/settlements")
@authenticated
def record_settlement(trip_id):
    trip_id = identifier(trip_id)
    data = parse(SettlementInput, error_status=400).model_dump(mode="json")
    require_trip(trip_id)
    data["paid_by"] = g.user_id
    return success(ExpenseRepository(g.db).create_settlement(trip_id, data), 201)
