"""Small domain data-access boundaries over the request-scoped Supabase adapter.

Authorization is deliberately not duplicated here: the adapter forwards the caller JWT and
PostgreSQL RLS remains the final authorization boundary.
"""


class ProfileRepository:
    def __init__(self, db): self.db = db
    def get(self, user_id): return self.db.one("profiles", {"id": user_id})
    def update(self, user_id, data): return self.db.update("profiles", {"id": user_id}, data)
    def search(self, query, limit=20):
        return self.db.rpc("search_public_profiles", {"p_query": query, "p_limit": limit})
    def username_available(self, username):
        return self.db.rpc("is_username_available", {"p_username": username})


class TripRepository:
    def __init__(self, db): self.db = db
    def create(self, data): return self.db.insert("trips", data)
    def list(self, page): return self.db.select("trips", **page)
    def get(self, trip_id): return self.db.one("trips", {"id": trip_id})
    def update(self, trip_id, data): return self.db.update("trips", {"id": trip_id}, data)
    def delete(self, trip_id): return self.db.delete("trips", {"id": trip_id})


class MembershipRepository:
    def __init__(self, db): self.db = db
    def list(self, trip_id, page): return self.db.select("trip_members", {"trip_id": trip_id}, **page)
    def get(self, trip_id, user_id): return self.db.one("trip_members", {"trip_id": trip_id, "user_id": user_id})
    def add(self, data): return self.db.insert("trip_members", data)
    def remove(self, trip_id, user_id): return self.db.delete("trip_members", {"trip_id": trip_id, "user_id": user_id})
    def public_list(self, trip_id): return self.db.rpc("list_trip_members_public", {"p_trip_id": trip_id})
    def remove_authorized(self, trip_id, user_id): return self.db.rpc("remove_trip_member", {"p_trip_id": trip_id, "p_user_id": user_id})
    def leave(self, trip_id): return self.db.rpc("leave_trip", {"p_trip_id": trip_id})


class InvitationRepository:
    def __init__(self, db): self.db = db
    def create(self, trip_id, user_id): return self.db.rpc("create_trip_invite", {"p_trip_id": trip_id, "p_invited_user_id": user_id})
    def mine(self): return self.db.rpc("list_my_trip_invites", {})
    def respond(self, invite_id, accept): return self.db.rpc("respond_trip_invite", {"p_invite_id": invite_id, "p_accept": accept})
    def search_candidates(self, trip_id, query): return self.db.rpc("search_trip_candidates", {"p_trip_id": trip_id, "p_query": query})


class ItineraryRepository:
    GRAPH = "*,itinerary_days(*,itinerary_activities(*))"
    def __init__(self, db): self.db = db
    def save(self, trip_id, data): return self.db.rpc("save_itinerary", {"p_trip_id": trip_id, "p_data": data})
    def save_ai_trip(self, trip, itinerary):
        return self.db.rpc("save_ai_trip", {"p_trip": trip, "p_itinerary": itinerary})
    def get(self, itinerary_id): return self.db.one("itineraries", {"id": itinerary_id}, select=self.GRAPH)
    def list(self, trip_id): return self.db.select("itineraries", {"trip_id": trip_id}, select=self.GRAPH)


class ExpenseRepository:
    def __init__(self, db): self.db = db
    def save(self, trip_id, data, expense_id=None):
        return self.db.rpc("save_expense", {"p_trip_id": trip_id, "p_data": data, "p_expense_id": expense_id})
    def get(self, expense_id): return self.db.one("expenses", {"id": expense_id})
    def list(self, trip_id, page):
        return self.db.select("expenses", {"trip_id": trip_id}, select="*,expense_participants(*)", **page)
    def delete(self, trip_id, expense_id):
        return self.db.rpc("delete_expense", {"p_trip_id": trip_id, "p_expense_id": expense_id})


class NotificationRepository:
    def __init__(self, db): self.db = db
    def list(self, user_id, page): return self.db.select("notifications", {"user_id": user_id}, **page)
    def get(self, notification_id, user_id):
        return self.db.one("notifications", {"id": notification_id, "user_id": user_id})
    def mark_read(self, notification_id, user_id, read_at):
        return self.db.update("notifications", {"id": notification_id, "user_id": user_id}, {"read_at": read_at})


class WishlistRepository:
    GRAPH = "*,saved_places(*)"
    def __init__(self, db): self.db = db
    def list(self, user_id, page):
        return self.db.select("wishlists", {"user_id": user_id}, select=self.GRAPH, **page)
    def get(self, wishlist_id, user_id):
        return self.db.one("wishlists", {"id": wishlist_id, "user_id": user_id}, select=self.GRAPH)
    def create(self, data): return self.db.insert("wishlists", data)
    def update(self, wishlist_id, user_id, data):
        return self.db.update("wishlists", {"id": wishlist_id, "user_id": user_id}, data)
    def delete(self, wishlist_id, user_id):
        return self.db.delete("wishlists", {"id": wishlist_id, "user_id": user_id})
    def add_place(self, data): return self.db.insert("saved_places", data)
    def remove_place(self, wishlist_id, place_id, user_id):
        return self.db.delete("saved_places", {"id": place_id, "wishlist_id": wishlist_id, "user_id": user_id})
