from flask import Blueprint, g

from app.middleware.auth_middleware import authenticated, require_trip
from app.repositories import InvitationRepository
from app.utils.responses import success
from app.utils.validators import MemberInput, identifier, parse

bp = Blueprint("invites", __name__)

@bp.post("/trips/<trip_id>/invites")
@authenticated
def create_invite(trip_id):
    trip_id = identifier(trip_id); target = parse(MemberInput)
    # The creator/owner is the only person allowed to invite travellers.
    # Database RPC authorization independently enforces the same rule.
    require_trip(trip_id, owner=True)
    return success(InvitationRepository(g.db).create(trip_id, str(target.user_id)), 201)

@bp.get("/trip-invites/me")
@authenticated
def my_invites():
    return success(InvitationRepository(g.db).mine())

@bp.post("/trip-invites/<invite_id>/accept")
@authenticated
def accept(invite_id):
    return success(InvitationRepository(g.db).respond(identifier(invite_id), True))

@bp.post("/trip-invites/<invite_id>/decline")
@authenticated
def decline(invite_id):
    return success(InvitationRepository(g.db).respond(identifier(invite_id), False))
