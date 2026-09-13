"""Small domain data-access boundaries over the request-scoped Supabase adapter.

Authorization is deliberately not duplicated here: the adapter forwards the caller JWT and
PostgreSQL RLS remains the final authorization boundary.
"""


class ProfileRepository:
    def __init__(self, db): self.db = db
    def get(self, user_id): return self.db.one("profiles", {"id": user_id})
    def update(self, user_id, data): return self.db.update("profiles", {"id": user_id}, data)


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
