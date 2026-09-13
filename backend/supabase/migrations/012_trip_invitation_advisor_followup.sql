-- Cover both invitation foreign keys and evaluate one SELECT policy per row.
create index trip_invites_invited_by_idx on public.trip_invites(invited_by);

drop policy if exists trip_invites_recipient_read on public.trip_invites;
drop policy if exists trip_invites_admin_read on public.trip_invites;
create policy trip_invites_read on public.trip_invites for select to authenticated
  using (
    invited_user_id = (select auth.uid())
    or (select private.is_trip_admin(trip_id))
  );
