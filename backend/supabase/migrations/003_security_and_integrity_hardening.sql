-- Additive hardening; does not reset or delete application data.
revoke all on function public.is_trip_member(uuid) from public, anon, authenticated;
revoke all on function public.is_trip_admin(uuid) from public, anon, authenticated;
revoke all on function public.is_trip_owner(uuid) from public, anon, authenticated;
revoke all on function public.add_trip_owner() from public, anon, authenticated;
revoke all on function public.create_profile() from public, anon, authenticated;
-- RLS expressions run with the caller's role, so authenticated requires EXECUTE on the
-- membership predicates. They only return booleans scoped to auth.uid().
grant execute on function public.is_trip_member(uuid) to authenticated;
grant execute on function public.is_trip_admin(uuid) to authenticated;
grant execute on function public.is_trip_owner(uuid) to authenticated;

create policy profiles_shared_trip_read on public.profiles for select to authenticated
using (
  id = (select auth.uid()) or exists (
    select 1 from public.trip_members mine
    join public.trip_members theirs on theirs.trip_id = mine.trip_id
    where mine.user_id = (select auth.uid()) and theirs.user_id = profiles.id
  )
);

create or replace function public.delete_expense(p_trip_id uuid, p_expense_id uuid)
returns boolean language plpgsql security definer set search_path = public as $$
declare v_role public.trip_role; v_creator uuid;
begin
  select role into v_role from public.trip_members where trip_id=p_trip_id and user_id=(select auth.uid());
  select created_by into v_creator from public.expenses where id=p_expense_id and trip_id=p_trip_id for update;
  if v_creator is null then raise exception 'expense not found' using errcode='P0002'; end if;
  if v_creator <> (select auth.uid()) and coalesce(v_role::text,'') not in ('owner','admin') then
    raise exception 'not allowed' using errcode='42501';
  end if;
  delete from public.expenses where id=p_expense_id and trip_id=p_trip_id;
  return true;
end $$;
revoke all on function public.delete_expense(uuid,uuid) from public, anon;
grant execute on function public.delete_expense(uuid,uuid) to authenticated;

revoke all on function public.save_expense(uuid,jsonb,uuid) from public, anon;
revoke all on function public.save_itinerary(uuid,jsonb) from public, anon;
grant execute on function public.save_expense(uuid,jsonb,uuid) to authenticated;
grant execute on function public.save_itinerary(uuid,jsonb) to authenticated;

create index if not exists trip_members_trip_role_idx on public.trip_members(trip_id,role,user_id);
create index if not exists expense_participants_user_idx on public.expense_participants(user_id,expense_id);
create index if not exists expenses_paid_by_idx on public.expenses(paid_by);
create index if not exists expenses_created_by_idx on public.expenses(created_by);
create index if not exists group_messages_sender_idx on public.group_messages(sender_id);
create index if not exists itineraries_generated_by_idx on public.itineraries(generated_by);
create index if not exists notifications_trip_idx on public.notifications(trip_id) where trip_id is not null;
create index if not exists itinerary_days_itinerary_idx on public.itinerary_days(itinerary_id,day_number);
create index if not exists itinerary_activities_day_idx on public.itinerary_activities(itinerary_day_id,position);
