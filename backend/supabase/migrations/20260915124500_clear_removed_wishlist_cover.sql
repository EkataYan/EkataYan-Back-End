-- A place-backed cover must not keep pointing at a saved place after that
-- place is removed. The delete and cover cleanup commit atomically.
create or replace function private.clear_removed_wishlist_cover()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  update public.wishlists
  set cover_path = null
  where id = old.wishlist_id
    and user_id = old.user_id
    and cover_path = old.external_place_id;
  return old;
end
$$;

revoke all on function private.clear_removed_wishlist_cover()
from public, anon, authenticated;

drop trigger if exists saved_place_cover_cleanup on public.saved_places;
create trigger saved_place_cover_cleanup
after delete on public.saved_places
for each row execute function private.clear_removed_wishlist_cover();
