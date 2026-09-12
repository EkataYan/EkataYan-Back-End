from flask import Blueprint, g

from app.middleware.auth_middleware import authenticated
from app.repositories import WishlistRepository
from app.utils.responses import success
from app.utils.validators import (
    SavedPlaceInput, WishlistInput, WishlistPatchInput, identifier, pagination, parse,
)

bp = Blueprint("wishlists", __name__)


@bp.get("/wishlists")
@authenticated
def list_wishlists():
    page = pagination()
    return success(WishlistRepository(g.db).list(g.user_id, page), pagination=page)


@bp.post("/wishlists")
@authenticated
def create_wishlist():
    data = parse(WishlistInput).model_dump(mode="json") | {"user_id": g.user_id}
    return success(WishlistRepository(g.db).create(data), 201)


@bp.get("/wishlists/<wishlist_id>")
@authenticated
def get_wishlist(wishlist_id):
    return success(WishlistRepository(g.db).get(identifier(wishlist_id), g.user_id))


@bp.patch("/wishlists/<wishlist_id>")
@authenticated
def update_wishlist(wishlist_id):
    data = parse(WishlistPatchInput).model_dump(mode="json", exclude_unset=True)
    return success(WishlistRepository(g.db).update(identifier(wishlist_id), g.user_id, data))


@bp.delete("/wishlists/<wishlist_id>")
@authenticated
def delete_wishlist(wishlist_id):
    WishlistRepository(g.db).delete(identifier(wishlist_id), g.user_id)
    return success({"deleted": True})


@bp.post("/wishlists/<wishlist_id>/places")
@authenticated
def add_place(wishlist_id):
    wishlist_id = identifier(wishlist_id)
    place = parse(SavedPlaceInput)
    repository = WishlistRepository(g.db)
    repository.get(wishlist_id, g.user_id)
    data = place.model_dump(mode="json") | {
        "wishlist_id": wishlist_id, "user_id": g.user_id,
    }
    return success(repository.add_place(data), 201)


@bp.delete("/wishlists/<wishlist_id>/places/<place_id>")
@authenticated
def remove_place(wishlist_id, place_id):
    WishlistRepository(g.db).remove_place(identifier(wishlist_id), identifier(place_id), g.user_id)
    return success({"deleted": True})
