-- Follow-up for live advisor findings after 004.
-- Public membership helpers are retained for migration compatibility but are no longer API-callable;
-- all active policies and RPCs use the equivalents in the non-exposed private schema.
revoke all on function public.is_trip_member(uuid) from public, anon, authenticated;
revoke all on function public.is_trip_admin(uuid) from public, anon, authenticated;
revoke all on function public.is_trip_owner(uuid) from public, anon, authenticated;

-- Cover both columns of the composite wishlist ownership foreign key.
create index if not exists saved_places_wishlist_user_idx
  on public.saved_places(wishlist_id, user_id);
