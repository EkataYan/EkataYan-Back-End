-- Public member/search RPCs expose only id, username, display_name and avatar.
-- Direct profile-table reads must remain owner-only so shared-trip membership
-- cannot reveal email, phone, bio or other private profile columns.
drop policy if exists profiles_read on public.profiles;
drop policy if exists profiles_shared_trip_read on public.profiles;
drop policy if exists profiles_own on public.profiles;
drop policy if exists profiles_read_own on public.profiles;
create policy profiles_read_own
on public.profiles
for select
to authenticated
using (id = (select auth.uid()));

drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own
on public.profiles
for update
to authenticated
using (id = (select auth.uid()))
with check (id = (select auth.uid()));
