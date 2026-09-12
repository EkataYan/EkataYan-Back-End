-- Additive EkataYan feature schema and least-privilege RLS hardening.
-- This migration preserves all existing rows and is safe for the deployed schema from 001-003.

create schema if not exists private;
revoke all on schema private from public, anon;
grant usage on schema private to authenticated;

create or replace function private.is_trip_member(p_trip_id uuid)
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.trip_members
    where trip_id = p_trip_id and user_id = (select auth.uid())
  )
$$;

create or replace function private.is_trip_admin(p_trip_id uuid)
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.trip_members
    where trip_id = p_trip_id and user_id = (select auth.uid()) and role in ('owner', 'admin')
  )
$$;

create or replace function private.is_trip_owner(p_trip_id uuid)
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.trip_members
    where trip_id = p_trip_id and user_id = (select auth.uid()) and role = 'owner'
  )
$$;

create or replace function private.shares_trip_with(p_user_id uuid)
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.trip_members mine
    join public.trip_members theirs on theirs.trip_id = mine.trip_id
    where mine.user_id = (select auth.uid()) and theirs.user_id = p_user_id
  )
$$;

revoke all on function private.is_trip_member(uuid) from public, anon;
revoke all on function private.is_trip_admin(uuid) from public, anon;
revoke all on function private.is_trip_owner(uuid) from public, anon;
revoke all on function private.shares_trip_with(uuid) from public, anon;
grant execute on function private.is_trip_member(uuid), private.is_trip_admin(uuid),
  private.is_trip_owner(uuid), private.shares_trip_with(uuid) to authenticated;

alter table public.trips add column if not exists status text not null default 'planned';
alter table public.itinerary_activities add column if not exists external_place_id text;
alter table public.itinerary_activities add column if not exists latitude numeric(9,6);
alter table public.itinerary_activities add column if not exists longitude numeric(9,6);
alter table public.itinerary_activities add column if not exists category text not null default 'other';
alter table public.expenses add column if not exists description text not null default '';
alter table public.expenses add column if not exists settlement_status text not null default 'open';
alter table public.expenses add column if not exists settled_at timestamptz;

do $$ begin
  alter table public.trips add constraint trips_status_check
    check (status in ('planned', 'ongoing', 'completed', 'cancelled'));
exception when duplicate_object then null; end $$;
do $$ begin
  alter table public.itinerary_activities add constraint activities_latitude_check
    check (latitude between -90 and 90);
exception when duplicate_object then null; end $$;
do $$ begin
  alter table public.itinerary_activities add constraint activities_longitude_check
    check (longitude between -180 and 180);
exception when duplicate_object then null; end $$;
do $$ begin
  alter table public.expenses add constraint expenses_description_length_check
    check (char_length(description) <= 2000);
exception when duplicate_object then null; end $$;
do $$ begin
  alter table public.expenses add constraint expenses_settlement_status_check
    check (settlement_status in ('open', 'settled'));
exception when duplicate_object then null; end $$;
do $$ begin
  alter table public.expenses add constraint expenses_settled_at_check
    check ((settlement_status = 'settled') = (settled_at is not null));
exception when duplicate_object then null; end $$;

create table if not exists public.wishlists (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 160),
  cover_path text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, user_id)
);

create table if not exists public.saved_places (
  id uuid primary key default gen_random_uuid(),
  wishlist_id uuid not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null default 'manual' check (char_length(provider) between 1 and 40),
  external_place_id text,
  name text not null check (char_length(name) between 1 and 200),
  location text not null default '',
  description text not null default '' check (char_length(description) <= 2000),
  latitude numeric(9,6) check (latitude between -90 and 90),
  longitude numeric(9,6) check (longitude between -180 and 180),
  image_url text,
  metadata jsonb not null default '{}'::jsonb check (jsonb_typeof(metadata) = 'object'),
  saved_at timestamptz not null default now(),
  constraint saved_places_wishlist_owner_fk foreign key (wishlist_id, user_id)
    references public.wishlists(id, user_id) on delete cascade,
  constraint saved_places_coordinate_pair_check check ((latitude is null) = (longitude is null))
);

create unique index if not exists wishlists_user_name_unique_idx
  on public.wishlists(user_id, lower(name));
create index if not exists wishlists_user_created_idx
  on public.wishlists(user_id, created_at desc);
create index if not exists saved_places_wishlist_saved_idx
  on public.saved_places(wishlist_id, saved_at desc);
create index if not exists saved_places_user_saved_idx
  on public.saved_places(user_id, saved_at desc);
create unique index if not exists saved_places_external_unique_idx
  on public.saved_places(wishlist_id, provider, external_place_id)
  where external_place_id is not null;
create index if not exists activities_external_place_idx
  on public.itinerary_activities(external_place_id) where external_place_id is not null;

drop trigger if exists wishlists_updated on public.wishlists;
create trigger wishlists_updated before update on public.wishlists
for each row execute function public.set_updated_at();

alter table public.wishlists enable row level security;
alter table public.saved_places enable row level security;

-- Replace recursive/public-helper policies with private membership predicates.
drop policy if exists profiles_own on public.profiles;
drop policy if exists profiles_shared_trip_read on public.profiles;
create policy profiles_read on public.profiles for select to authenticated
  using (id = (select auth.uid()) or (select private.shares_trip_with(id)));
create policy profiles_update_own on public.profiles for update to authenticated
  using (id = (select auth.uid())) with check (id = (select auth.uid()));

drop policy if exists trips_read on public.trips;
drop policy if exists trips_update on public.trips;
drop policy if exists trips_delete on public.trips;
create policy trips_read on public.trips for select to authenticated
  using ((select private.is_trip_member(id)));
create policy trips_update on public.trips for update to authenticated
  using ((select private.is_trip_admin(id))) with check ((select private.is_trip_admin(id)));
create policy trips_delete on public.trips for delete to authenticated
  using ((select private.is_trip_owner(id)));

drop policy if exists members_read on public.trip_members;
drop policy if exists members_write on public.trip_members;
create policy members_read on public.trip_members for select to authenticated
  using ((select private.is_trip_member(trip_id)));
create policy members_insert on public.trip_members for insert to authenticated
  with check ((select private.is_trip_owner(trip_id)) and role <> 'owner');
create policy members_update on public.trip_members for update to authenticated
  using ((select private.is_trip_owner(trip_id)) and role <> 'owner')
  with check ((select private.is_trip_owner(trip_id)) and role <> 'owner');
create policy members_delete on public.trip_members for delete to authenticated
  using ((select private.is_trip_owner(trip_id)) and role <> 'owner');

drop policy if exists itineraries_read on public.itineraries;
create policy itineraries_read on public.itineraries for select to authenticated
  using ((select private.is_trip_member(trip_id)));
drop policy if exists itinerary_days_read on public.itinerary_days;
create policy itinerary_days_read on public.itinerary_days for select to authenticated using (
  exists (select 1 from public.itineraries i where i.id = itinerary_id
    and (select private.is_trip_member(i.trip_id)))
);
drop policy if exists itinerary_activities_read on public.itinerary_activities;
create policy itinerary_activities_read on public.itinerary_activities for select to authenticated using (
  exists (select 1 from public.itinerary_days d join public.itineraries i on i.id = d.itinerary_id
    where d.id = itinerary_day_id and (select private.is_trip_member(i.trip_id)))
);
drop policy if exists expenses_read on public.expenses;
create policy expenses_read on public.expenses for select to authenticated
  using ((select private.is_trip_member(trip_id)));
drop policy if exists participants_read on public.expense_participants;
create policy participants_read on public.expense_participants for select to authenticated using (
  exists (select 1 from public.expenses e where e.id = expense_id
    and (select private.is_trip_member(e.trip_id)))
);
drop policy if exists messages_read on public.group_messages;
drop policy if exists messages_create on public.group_messages;
create policy messages_read on public.group_messages for select to authenticated
  using ((select private.is_trip_member(trip_id)));
create policy messages_create on public.group_messages for insert to authenticated
  with check ((select private.is_trip_member(trip_id)) and sender_id = (select auth.uid()));

create policy wishlists_own on public.wishlists for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy saved_places_own on public.saved_places for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists trip_images_member_read on storage.objects;
drop policy if exists trip_images_member_insert on storage.objects;
create policy trip_images_member_read on storage.objects for select to authenticated using (
  bucket_id = 'trip-images' and (select private.is_trip_member(((storage.foldername(name))[1])::uuid))
);
create policy trip_images_member_insert on storage.objects for insert to authenticated with check (
  bucket_id = 'trip-images' and (select private.is_trip_member(((storage.foldername(name))[1])::uuid))
);

-- Existing RPCs remain the only financial and itinerary write surface.
create or replace function public.save_expense(p_trip_id uuid, p_data jsonb, p_expense_id uuid default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_id uuid := coalesce(p_expense_id, gen_random_uuid()); v_amount numeric(14,2); v_paid_by uuid; v_count integer; v_total numeric(14,2); v_role public.trip_role; v_row public.expenses%rowtype; v_result jsonb;
begin
  select role into v_role from public.trip_members where trip_id=p_trip_id and user_id=(select auth.uid());
  if v_role is null then raise exception 'not a trip member' using errcode='42501'; end if;
  v_amount := (p_data->>'amount')::numeric(14,2); v_paid_by := (p_data->>'paid_by')::uuid;
  if v_amount <= 0 or not exists(select 1 from public.trip_members where trip_id=p_trip_id and user_id=v_paid_by) then raise exception 'invalid expense' using errcode='22023'; end if;
  select count(*), coalesce(sum((x->>'share')::numeric(14,2)),0) into v_count,v_total from jsonb_array_elements(p_data->'participants') x;
  if v_count < 1 or v_total <> v_amount or v_count <> (select count(distinct (x->>'user_id')::uuid) from jsonb_array_elements(p_data->'participants') x) or exists(select 1 from jsonb_array_elements(p_data->'participants') x where not exists(select 1 from public.trip_members m where m.trip_id=p_trip_id and m.user_id=(x->>'user_id')::uuid)) then raise exception 'invalid participants' using errcode='22023'; end if;
  if p_data->>'split_type'='equal' and exists(select 1 from jsonb_array_elements(p_data->'participants') x where (x->>'share')::numeric(14,2) not in (trunc(v_amount/v_count,2), trunc(v_amount/v_count,2)+.01)) then raise exception 'invalid equal split' using errcode='22023'; end if;
  if p_expense_id is not null then
    select * into v_row from public.expenses where id=p_expense_id and trip_id=p_trip_id for update;
    if not found or (v_row.created_by <> (select auth.uid()) and v_role not in ('owner','admin')) then raise exception 'not allowed' using errcode='42501'; end if;
    delete from public.expense_participants where expense_id=v_id;
    update public.expenses set title=p_data->>'title', description=coalesce(p_data->>'description',''), amount=v_amount,currency=p_data->>'currency',category=p_data->>'category',paid_by=v_paid_by,split_type=(p_data->>'split_type')::public.expense_split_type,incurred_at=(p_data->>'incurred_at')::timestamptz where id=v_id;
  else
    insert into public.expenses(id,trip_id,title,description,amount,currency,category,paid_by,split_type,incurred_at,created_by) values(v_id,p_trip_id,p_data->>'title',coalesce(p_data->>'description',''),v_amount,p_data->>'currency',p_data->>'category',v_paid_by,(p_data->>'split_type')::public.expense_split_type,(p_data->>'incurred_at')::timestamptz,(select auth.uid()));
  end if;
  insert into public.expense_participants(expense_id,user_id,share) select v_id,(x->>'user_id')::uuid,(x->>'share')::numeric(14,2) from jsonb_array_elements(p_data->'participants') x;
  select to_jsonb(e) || jsonb_build_object('expense_participants',(select coalesce(jsonb_agg(ep), '[]'::jsonb) from public.expense_participants ep where ep.expense_id=e.id)) into v_result from public.expenses e where e.id=v_id;
  return v_result;
end $$;

create or replace function public.save_itinerary(p_trip_id uuid, p_data jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_itinerary uuid := gen_random_uuid(); v_day jsonb; v_activity jsonb; v_day_id uuid; v_position smallint;
begin
  if not private.is_trip_admin(p_trip_id) then raise exception 'not allowed' using errcode='42501'; end if;
  insert into public.itineraries(id,trip_id,overview,currency,recommendations,generated_by) values(v_itinerary,p_trip_id,p_data->>'overview',p_data->>'currency',array(select jsonb_array_elements_text(coalesce(p_data->'recommendations','[]'))),(select auth.uid()));
  for v_day in select * from jsonb_array_elements(p_data->'days') loop
    insert into public.itinerary_days(itinerary_id,day_number,trip_date,locations,notes) values(v_itinerary,(v_day->>'day_number')::smallint,(v_day->>'date')::date,array(select jsonb_array_elements_text(v_day->'locations')),coalesce(v_day->>'notes','')) returning id into v_day_id;
    v_position := 0;
    for v_activity in select * from jsonb_array_elements(v_day->'activities') loop
      v_position := v_position+1;
      insert into public.itinerary_activities(itinerary_day_id,position,title,location,suggested_time,description,estimated_cost,transport,notes,external_place_id,latitude,longitude,category)
      values(v_day_id,v_position,v_activity->>'title',v_activity->>'location',(v_activity->>'suggested_time')::time,v_activity->>'description',(v_activity->>'estimated_cost')::numeric(14,2),v_activity->>'transport',coalesce(v_activity->>'notes',''),nullif(v_activity->>'external_place_id',''),nullif(v_activity->>'latitude','')::numeric(9,6),nullif(v_activity->>'longitude','')::numeric(9,6),coalesce(nullif(v_activity->>'category',''),'other'));
    end loop;
  end loop;
  return (select to_jsonb(i) from public.itineraries i where i.id=v_itinerary);
end $$;

-- Default grants on older projects are broad. Make the application API surface explicit.
revoke all on all tables in schema public from anon;
revoke all on all tables in schema public from authenticated;
grant select, update on public.profiles to authenticated;
grant select, insert, update, delete on public.trips, public.trip_members to authenticated;
grant select on public.itineraries, public.itinerary_days, public.itinerary_activities,
  public.expenses, public.expense_participants to authenticated;
grant select, insert on public.group_messages to authenticated;
grant select on public.notifications to authenticated;
grant update(read_at) on public.notifications to authenticated;
grant select, insert, update, delete on public.wishlists, public.saved_places to authenticated;

revoke all on function public.save_expense(uuid,jsonb,uuid) from public, anon;
revoke all on function public.save_itinerary(uuid,jsonb) from public, anon;
grant execute on function public.save_expense(uuid,jsonb,uuid), public.save_itinerary(uuid,jsonb) to authenticated;

alter default privileges for role postgres in schema public revoke all on tables from anon;
alter default privileges for role postgres in schema public revoke execute on functions from public, anon;

update storage.buckets
set file_size_limit = 5242880,
    allowed_mime_types = array['image/jpeg','image/png','image/webp']
where id in ('profile-images','trip-images');

