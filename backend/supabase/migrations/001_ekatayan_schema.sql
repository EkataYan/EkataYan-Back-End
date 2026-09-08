-- Run in the Supabase SQL editor or with `supabase db push`.
-- This migration assumes a standard Supabase project with auth.users and storage schema.
create extension if not exists pgcrypto;

create type public.trip_role as enum ('owner', 'admin', 'member');
create type public.expense_split_type as enum ('equal', 'exact');

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null default '',
  bio text not null default '' check (char_length(bio) <= 1000),
  home_city text not null default '',
  language text not null default 'en' check (language in ('en', 'si', 'ta')),
  interests text[] not null default '{}',
  avatar_path text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.trips (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 1 and 160),
  destinations text[] not null check (cardinality(destinations) between 1 and 20),
  start_date date not null,
  end_date date not null check (end_date >= start_date and end_date <= start_date + 29),
  budget numeric(14,2) not null check (budget >= 0),
  currency text not null default 'LKR' check (currency in ('LKR','USD','EUR','GBP','INR','AUD')),
  travelers smallint not null default 1 check (travelers between 1 and 100),
  interests text[] not null default '{}',
  preferred_activities text[] not null default '{}',
  travel_style text not null default 'balanced',
  accommodation_preference text not null default 'any',
  transportation_preference text not null default 'any',
  additional_requirements text not null default '',
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.trip_members (
  trip_id uuid not null references public.trips(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete restrict,
  role public.trip_role not null default 'member',
  joined_at timestamptz not null default now(),
  primary key (trip_id, user_id)
);

create table public.itineraries (
  id uuid primary key default gen_random_uuid(),
  trip_id uuid not null references public.trips(id) on delete cascade,
  overview text not null,
  currency text not null check (currency in ('LKR','USD','EUR','GBP','INR','AUD')),
  recommendations text[] not null default '{}',
  generated_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table public.itinerary_days (
  id uuid primary key default gen_random_uuid(),
  itinerary_id uuid not null references public.itineraries(id) on delete cascade,
  day_number smallint not null check (day_number between 1 and 30),
  trip_date date not null,
  locations text[] not null check (cardinality(locations) >= 1),
  notes text not null default '',
  unique (itinerary_id, day_number)
);
create table public.itinerary_activities (
  id uuid primary key default gen_random_uuid(),
  itinerary_day_id uuid not null references public.itinerary_days(id) on delete cascade,
  position smallint not null check (position >= 1),
  title text not null, location text not null, suggested_time time not null,
  description text not null, estimated_cost numeric(14,2) not null check (estimated_cost >= 0),
  transport text not null, notes text not null default '',
  unique (itinerary_day_id, position)
);

create table public.expenses (
  id uuid primary key default gen_random_uuid(),
  trip_id uuid not null references public.trips(id) on delete cascade,
  title text not null, amount numeric(14,2) not null check (amount > 0),
  currency text not null check (currency in ('LKR','USD','EUR','GBP','INR','AUD')),
  category text not null default 'other',
  paid_by uuid not null references auth.users(id) on delete restrict,
  split_type public.expense_split_type not null,
  incurred_at timestamptz not null,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.expense_participants (
  expense_id uuid not null references public.expenses(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete restrict,
  share numeric(14,2) not null check (share >= 0),
  primary key (expense_id, user_id)
);

create table public.group_messages (
  id uuid primary key default gen_random_uuid(),
  trip_id uuid not null references public.trips(id) on delete cascade,
  sender_id uuid not null references auth.users(id) on delete restrict,
  content text not null check (char_length(content) between 1 and 4000),
  created_at timestamptz not null default now()
);
create table public.notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  trip_id uuid references public.trips(id) on delete cascade,
  type text not null check (char_length(type) between 1 and 80),
  title text not null check (char_length(title) between 1 and 200),
  body text not null default '',
  payload jsonb not null default '{}'::jsonb,
  read_at timestamptz,
  created_at timestamptz not null default now()
);

create index trips_created_by_idx on public.trips(created_by);
create index trip_members_user_idx on public.trip_members(user_id, trip_id);
create index itineraries_trip_idx on public.itineraries(trip_id, created_at desc);
create index expenses_trip_idx on public.expenses(trip_id, incurred_at desc);
create index messages_trip_idx on public.group_messages(trip_id, created_at desc);
create index notifications_user_idx on public.notifications(user_id, read_at, created_at desc);

create or replace function public.set_updated_at() returns trigger language plpgsql set search_path = public as $$
begin new.updated_at = now(); return new; end $$;
create trigger profiles_updated before update on public.profiles for each row execute function public.set_updated_at();
create trigger trips_updated before update on public.trips for each row execute function public.set_updated_at();
create trigger itineraries_updated before update on public.itineraries for each row execute function public.set_updated_at();
create trigger expenses_updated before update on public.expenses for each row execute function public.set_updated_at();
create or replace function public.prevent_trip_owner_change() returns trigger language plpgsql set search_path = public as $$
begin if new.created_by <> old.created_by then raise exception 'trip owner cannot change' using errcode='42501'; end if; return new; end $$;
create trigger trips_owner_immutable before update on public.trips for each row execute function public.prevent_trip_owner_change();

create or replace function public.create_profile() returns trigger language plpgsql security definer set search_path = public as $$
begin insert into public.profiles(id, display_name) values (new.id, coalesce(new.raw_user_meta_data->>'full_name','')) on conflict (id) do nothing; return new; end $$;
create trigger auth_user_profile after insert on auth.users for each row execute function public.create_profile();
-- Existing projects: run once after migration to backfill profiles.
insert into public.profiles(id, display_name) select id, coalesce(raw_user_meta_data->>'full_name','') from auth.users on conflict (id) do nothing;

create or replace function public.add_trip_owner() returns trigger language plpgsql security definer set search_path = public as $$
begin insert into public.trip_members(trip_id,user_id,role) values (new.id,new.created_by,'owner'); return new; end $$;
create trigger trip_owner_member after insert on public.trips for each row execute function public.add_trip_owner();

create or replace function public.is_trip_member(p_trip_id uuid) returns boolean language sql stable security definer set search_path = public as $$
  select exists(select 1 from public.trip_members where trip_id=p_trip_id and user_id=(select auth.uid())) $$;
create or replace function public.is_trip_admin(p_trip_id uuid) returns boolean language sql stable security definer set search_path = public as $$
  select exists(select 1 from public.trip_members where trip_id=p_trip_id and user_id=(select auth.uid()) and role in ('owner','admin')) $$;
create or replace function public.is_trip_owner(p_trip_id uuid) returns boolean language sql stable security definer set search_path = public as $$
  select exists(select 1 from public.trip_members where trip_id=p_trip_id and user_id=(select auth.uid()) and role='owner') $$;

alter table public.profiles enable row level security;
alter table public.trips enable row level security;
alter table public.trip_members enable row level security;
alter table public.itineraries enable row level security;
alter table public.itinerary_days enable row level security;
alter table public.itinerary_activities enable row level security;
alter table public.expenses enable row level security;
alter table public.expense_participants enable row level security;
alter table public.group_messages enable row level security;
alter table public.notifications enable row level security;

create policy profiles_own on public.profiles for all to authenticated using (id=(select auth.uid())) with check (id=(select auth.uid()));
create policy trips_read on public.trips for select to authenticated using (public.is_trip_member(id));
create policy trips_create on public.trips for insert to authenticated with check (created_by=(select auth.uid()));
create policy trips_update on public.trips for update to authenticated using (public.is_trip_admin(id)) with check (public.is_trip_admin(id));
create policy trips_delete on public.trips for delete to authenticated using (public.is_trip_owner(id));
create policy members_read on public.trip_members for select to authenticated using (public.is_trip_member(trip_id));
create policy members_write on public.trip_members for all to authenticated using (public.is_trip_owner(trip_id)) with check (public.is_trip_owner(trip_id));
create policy itineraries_read on public.itineraries for select to authenticated using (public.is_trip_member(trip_id));
create policy itinerary_days_read on public.itinerary_days for select to authenticated using (exists(select 1 from public.itineraries i where i.id=itinerary_id and public.is_trip_member(i.trip_id)));
create policy itinerary_activities_read on public.itinerary_activities for select to authenticated using (exists(select 1 from public.itinerary_days d join public.itineraries i on i.id=d.itinerary_id where d.id=itinerary_day_id and public.is_trip_member(i.trip_id)));
create policy expenses_read on public.expenses for select to authenticated using (public.is_trip_member(trip_id));
create policy participants_read on public.expense_participants for select to authenticated using (exists(select 1 from public.expenses e where e.id=expense_id and public.is_trip_member(e.trip_id)));
create policy messages_read on public.group_messages for select to authenticated using (public.is_trip_member(trip_id));
create policy messages_create on public.group_messages for insert to authenticated with check (public.is_trip_member(trip_id) and sender_id=(select auth.uid()));
create policy notifications_own on public.notifications for select to authenticated using (user_id=(select auth.uid()));
create policy notifications_read on public.notifications for update to authenticated using (user_id=(select auth.uid())) with check (user_id=(select auth.uid()));

-- Financial rows and itinerary nested writes are RPC-only. This prevents incomplete split rows.
create or replace function public.save_expense(p_trip_id uuid, p_data jsonb, p_expense_id uuid default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_id uuid := coalesce(p_expense_id, gen_random_uuid()); v_amount numeric(14,2); v_paid_by uuid; v_count integer; v_total numeric(14,2); v_role public.trip_role; v_row public.expenses%rowtype; v_result jsonb;
begin
  select role into v_role from public.trip_members where trip_id=p_trip_id and user_id=auth.uid();
  if v_role is null then raise exception 'not a trip member' using errcode='42501'; end if;
  v_amount := (p_data->>'amount')::numeric(14,2); v_paid_by := (p_data->>'paid_by')::uuid;
  if v_amount <= 0 or not exists(select 1 from public.trip_members where trip_id=p_trip_id and user_id=v_paid_by) then raise exception 'invalid expense' using errcode='22023'; end if;
  select count(*), coalesce(sum((x->>'share')::numeric(14,2)),0) into v_count,v_total from jsonb_array_elements(p_data->'participants') x;
  if v_count < 1 or v_total <> v_amount or v_count <> (select count(distinct (x->>'user_id')::uuid) from jsonb_array_elements(p_data->'participants') x) or exists(select 1 from jsonb_array_elements(p_data->'participants') x where not exists(select 1 from public.trip_members m where m.trip_id=p_trip_id and m.user_id=(x->>'user_id')::uuid)) then raise exception 'invalid participants' using errcode='22023'; end if;
  if p_data->>'split_type'='equal' and exists(select 1 from jsonb_array_elements(p_data->'participants') x where (x->>'share')::numeric(14,2) not in (trunc(v_amount/v_count,2), trunc(v_amount/v_count,2)+.01)) then raise exception 'invalid equal split' using errcode='22023'; end if;
  if p_expense_id is not null then select * into v_row from public.expenses where id=p_expense_id and trip_id=p_trip_id for update; if not found or (v_row.created_by <> auth.uid() and v_role not in ('owner','admin')) then raise exception 'not allowed' using errcode='42501'; end if; delete from public.expense_participants where expense_id=v_id; update public.expenses set title=p_data->>'title',amount=v_amount,currency=p_data->>'currency',category=p_data->>'category',paid_by=v_paid_by,split_type=(p_data->>'split_type')::public.expense_split_type,incurred_at=(p_data->>'incurred_at')::timestamptz where id=v_id;
  else insert into public.expenses(id,trip_id,title,amount,currency,category,paid_by,split_type,incurred_at,created_by) values(v_id,p_trip_id,p_data->>'title',v_amount,p_data->>'currency',p_data->>'category',v_paid_by,(p_data->>'split_type')::public.expense_split_type,(p_data->>'incurred_at')::timestamptz,auth.uid()); end if;
  insert into public.expense_participants(expense_id,user_id,share) select v_id,(x->>'user_id')::uuid,(x->>'share')::numeric(14,2) from jsonb_array_elements(p_data->'participants') x;
  select to_jsonb(e) || jsonb_build_object('expense_participants',(select coalesce(jsonb_agg(ep), '[]'::jsonb) from public.expense_participants ep where ep.expense_id=e.id)) into v_result from public.expenses e where e.id=v_id;
  return v_result;
end $$;

create or replace function public.save_itinerary(p_trip_id uuid, p_data jsonb) returns jsonb language plpgsql security definer set search_path = public as $$
declare v_itinerary uuid := gen_random_uuid(); v_day jsonb; v_activity jsonb; v_day_id uuid; v_position smallint;
begin
  if not public.is_trip_admin(p_trip_id) then raise exception 'not allowed' using errcode='42501'; end if;
  insert into public.itineraries(id,trip_id,overview,currency,recommendations,generated_by) values(v_itinerary,p_trip_id,p_data->>'overview',p_data->>'currency',array(select jsonb_array_elements_text(coalesce(p_data->'recommendations','[]'))),auth.uid());
  for v_day in select * from jsonb_array_elements(p_data->'days') loop
    insert into public.itinerary_days(itinerary_id,day_number,trip_date,locations,notes) values(v_itinerary,(v_day->>'day_number')::smallint,(v_day->>'date')::date,array(select jsonb_array_elements_text(v_day->'locations')),coalesce(v_day->>'notes','')) returning id into v_day_id; v_position := 0;
    for v_activity in select * from jsonb_array_elements(v_day->'activities') loop v_position := v_position+1; insert into public.itinerary_activities(itinerary_day_id,position,title,location,suggested_time,description,estimated_cost,transport,notes) values(v_day_id,v_position,v_activity->>'title',v_activity->>'location',(v_activity->>'suggested_time')::time,v_activity->>'description',(v_activity->>'estimated_cost')::numeric(14,2),v_activity->>'transport',coalesce(v_activity->>'notes','')); end loop;
  end loop;
  return (select to_jsonb(i) from public.itineraries i where i.id=v_itinerary);
end $$;

grant usage on schema public to authenticated;
grant select,insert,update,delete on public.profiles,public.trips,public.trip_members,public.group_messages to authenticated;
grant select on public.itineraries,public.itinerary_days,public.itinerary_activities,public.expenses,public.expense_participants,public.notifications to authenticated;
grant update(read_at) on public.notifications to authenticated;
grant execute on function public.save_expense(uuid,jsonb,uuid), public.save_itinerary(uuid,jsonb) to authenticated;

-- Create private buckets in Dashboard or uncomment if running with an owner role:
-- insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types) values
-- ('profile-images','profile-images',false,5242880,array['image/jpeg','image/png','image/webp']),
-- ('trip-images','trip-images',false,5242880,array['image/jpeg','image/png','image/webp']);
create policy profile_images_owner on storage.objects for all to authenticated using (bucket_id='profile-images' and (storage.foldername(name))[1]=(select auth.uid()::text)) with check (bucket_id='profile-images' and (storage.foldername(name))[1]=(select auth.uid()::text));
create policy trip_images_member_read on storage.objects for select to authenticated using (bucket_id='trip-images' and public.is_trip_member(((storage.foldername(name))[1])::uuid));
create policy trip_images_member_insert on storage.objects for insert to authenticated with check (bucket_id='trip-images' and public.is_trip_member(((storage.foldername(name))[1])::uuid));
