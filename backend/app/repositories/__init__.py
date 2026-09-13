"""Supabase-backed domain repositories used by Flask routes and services."""

from app.repositories.supabase_repositories import (
    ExpenseRepository,
    InvitationRepository,
    ItineraryRepository,
    MembershipRepository,
    NotificationRepository,
    ProfileRepository,
    TripRepository,
    WishlistRepository,
)

__all__ = [
    "ExpenseRepository", "InvitationRepository", "ItineraryRepository", "MembershipRepository",
    "NotificationRepository", "ProfileRepository", "TripRepository", "WishlistRepository",
]
