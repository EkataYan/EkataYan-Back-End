-- INSERT ... RETURNING must be able to see the new trip before the AFTER INSERT owner-membership
-- trigger has completed. created_by is immutable, so it is a safe owner visibility predicate.
drop policy if exists trips_read on public.trips;
create policy trips_read on public.trips for select to authenticated
using (created_by = (select auth.uid()) or (select private.is_trip_member(id)));
