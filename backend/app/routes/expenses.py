from flask import Blueprint, g
from app.middleware.auth_middleware import authenticated, require_trip
from app.utils.responses import APIError, success
from app.utils.validators import ExpenseInput, identifier, pagination, parse

bp = Blueprint("expenses", __name__)


@bp.post("/trips/<trip_id>/expenses")
@authenticated
def create(trip_id):
    trip_id = identifier(trip_id)
    data = parse(ExpenseInput).model_dump(mode="json")
    require_trip(trip_id)
    return success(g.db.rpc("save_expense", {"p_trip_id": trip_id, "p_data": data, "p_expense_id": None}), 201)


@bp.get("/trips/<trip_id>/expenses")
@authenticated
def list_expenses(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id)
    page = pagination()
    return success(g.db.select("expenses", {"trip_id": trip_id}, select="*,expense_participants(*)", **page), pagination=page)


def editable(expense_id):
    expense = g.db.one("expenses", {"id": expense_id})
    require_trip(expense["trip_id"], admin=expense["created_by"] != g.user_id)
    return expense


@bp.put("/expenses/<expense_id>")
@authenticated
def update(expense_id):
    expense_id = identifier(expense_id)
    data = parse(ExpenseInput).model_dump(mode="json")
    expense = editable(expense_id)
    return success(g.db.rpc("save_expense", {"p_trip_id": expense["trip_id"], "p_data": data, "p_expense_id": expense_id}))


@bp.delete("/expenses/<expense_id>")
@authenticated
def delete(expense_id):
    expense_id = identifier(expense_id)
    editable(expense_id)
    g.db.delete("expenses", {"id": expense_id})
    return success({"deleted": True})
