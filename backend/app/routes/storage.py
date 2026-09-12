from flask import Blueprint, Response, current_app, g, request

from app.middleware.auth_middleware import authenticated, require_trip
from app.repositories import ProfileRepository
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
    repository = ProfileRepository(g.db)
    previous_path = repository.get(g.user_id).get("avatar_path")
    storage = StorageService(g.db)
    result = storage.upload_private_image("profile-images", g.user_id, upload_file())
    profile = repository.update(g.user_id, {"avatar_path": result["path"]})
    if previous_path and previous_path != result["path"]:
        try:
            storage.delete_private_image("profile-images", g.user_id, previous_path)
        except APIError:
            current_app.logger.warning("Previous profile image cleanup failed for user uuid=%s", g.user_id)
    return success({"profile": profile, "upload": result}, 201)


@bp.get("/storage/profile-picture")
@authenticated
def get_profile_picture():
    profile = ProfileRepository(g.db).get(g.user_id)
    path = profile.get("avatar_path")
    if not path:
        raise APIError("NOT_FOUND", "Profile picture was not found.", 404)
    raw, mime = StorageService(g.db).download_private_image("profile-images", g.user_id, path)
    return Response(raw, status=200, content_type=mime)


@bp.post("/trips/<trip_id>/images")
@authenticated
def trip_image(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id)
    result = StorageService(g.db).upload_private_image("trip-images", trip_id, upload_file())
    return success(result, 201)
