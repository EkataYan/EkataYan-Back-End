from flask import Blueprint, g
from app.middleware.auth_middleware import authenticated, require_trip
from app.repositories import ExpenseRepository
from app.utils.responses import APIError, success
from app.utils.validators import ExpenseInput, identifier, pagination, parse

bp = Blueprint("expenses", __name__)


@bp.post("/trips/<trip_id>/expenses")
@authenticated
def create(trip_id):
    trip_id = identifier(trip_id)
    data = parse(ExpenseInput).model_dump(mode="json")
    require_trip(trip_id)
    return success(ExpenseRepository(g.db).save(trip_id, data), 201)


@bp.get("/trips/<trip_id>/expenses")
@authenticated
def list_expenses(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id)
    page = pagination()
    return success(ExpenseRepository(g.db).list(trip_id, page), pagination=page)


def editable(expense_id):
    expense = ExpenseRepository(g.db).get(expense_id)
    require_trip(expense["trip_id"], admin=expense["created_by"] != g.user_id)
    return expense


@bp.put("/expenses/<expense_id>")
@authenticated
def update(expense_id):
    expense_id = identifier(expense_id)
    data = parse(ExpenseInput).model_dump(mode="json")
    expense = editable(expense_id)
    return success(ExpenseRepository(g.db).save(expense["trip_id"], data, expense_id))


@bp.delete("/expenses/<expense_id>")
@authenticated
def delete(expense_id):
    expense_id = identifier(expense_id)
    expense = editable(expense_id)
    ExpenseRepository(g.db).delete(expense["trip_id"], expense_id)
    return success({"deleted": True})
