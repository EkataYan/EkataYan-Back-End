-- Produce durable in-app notifications for important shared-trip events.
create or replace function private.notify_trip_member_added()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.role <> 'owner' then
    insert into public.notifications(user_id, trip_id, type, title, body, payload)
    select new.user_id, new.trip_id, 'trip_member_added', 'Added to a trip',
           'You were added to ' || t.name,
           jsonb_build_object('trip_id', new.trip_id, 'role', new.role)
    from public.trips t where t.id = new.trip_id;
  end if;
  return new;
end $$;

create or replace function private.notify_itinerary_created()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.notifications(user_id, trip_id, type, title, body, payload)
  select m.user_id, new.trip_id, 'itinerary_generated', 'Itinerary ready',
         'A new itinerary is ready for ' || t.name,
         jsonb_build_object('trip_id', new.trip_id, 'itinerary_id', new.id)
  from public.trip_members m join public.trips t on t.id = m.trip_id
  where m.trip_id = new.trip_id and m.user_id <> new.generated_by;
  return new;
end $$;

create or replace function private.notify_expense_created()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.notifications(user_id, trip_id, type, title, body, payload)
  select m.user_id, new.trip_id, 'expense_added', 'Expense added',
         new.title || ' was added to ' || t.name,
         jsonb_build_object('trip_id', new.trip_id, 'expense_id', new.id)
  from public.trip_members m join public.trips t on t.id = m.trip_id
  where m.trip_id = new.trip_id and m.user_id <> new.created_by;
  return new;
end $$;

revoke all on function private.notify_trip_member_added() from public, anon, authenticated;
revoke all on function private.notify_itinerary_created() from public, anon, authenticated;
revoke all on function private.notify_expense_created() from public, anon, authenticated;

drop trigger if exists trip_member_added_notification on public.trip_members;
create trigger trip_member_added_notification after insert on public.trip_members
for each row execute function private.notify_trip_member_added();
drop trigger if exists itinerary_created_notification on public.itineraries;
create trigger itinerary_created_notification after insert on public.itineraries
for each row execute function private.notify_itinerary_created();
drop trigger if exists expense_created_notification on public.expenses;
create trigger expense_created_notification after insert on public.expenses
for each row execute function private.notify_expense_created();
