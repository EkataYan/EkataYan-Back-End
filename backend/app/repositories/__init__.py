"""Supabase-backed domain repositories used by Flask routes and services."""

from app.repositories.supabase_repositories import (
    ExpenseRepository,
    ItineraryRepository,
    MembershipRepository,
    NotificationRepository,
    ProfileRepository,
    TripRepository,
    WishlistRepository,
)

__all__ = [
    "ExpenseRepository", "ItineraryRepository", "MembershipRepository",
    "NotificationRepository", "ProfileRepository", "TripRepository", "WishlistRepository",
]
