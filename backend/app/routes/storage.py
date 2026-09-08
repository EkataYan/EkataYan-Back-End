from flask import Blueprint, g, request

from app.middleware.auth_middleware import authenticated, require_trip
from app.services.storage_service import StorageService
from app.utils.responses import APIError, success
from app.utils.validators import identifier

bp = Blueprint("storage", __name__)


def upload_file():
    file = request.files.get("file")
    if file is None or not file.filename:
        raise APIError("INVALID_FILE", "A file form field is required.", 422)
    return file


@bp.post("/storage/profile-picture")
@authenticated
def profile_picture():
    result = StorageService(g.db).upload_private_image("profile-images", g.user_id, upload_file())
    profile = g.db.update("profiles", {"id": g.user_id}, {"avatar_path": result["path"]})
    return success({"profile": profile, "upload": result}, 201)


@bp.post("/trips/<trip_id>/images")
@authenticated
def trip_image(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id)
    result = StorageService(g.db).upload_private_image("trip-images", trip_id, upload_file())
    return success(result, 201)
