-- Apply this migration to projects where 001_ekatayan_schema.sql was already run.
-- New projects receive the same schema directly from migration 001.
alter table public.profiles add column if not exists email text not null default '';
alter table public.profiles add column if not exists phone text not null default '';

create or replace function public.create_profile() returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles(id, display_name, email, phone)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', ''),
    coalesce(new.email, ''),
    coalesce(new.raw_user_meta_data->>'phone', new.phone, '')
  )
  on conflict (id) do update set
    display_name = excluded.display_name,
    email = excluded.email,
    phone = excluded.phone;
  raise log 'profile provisioned for auth user %', new.id;
  return new;
end
$$;

-- Backfill users created before profile provisioning/contact persistence existed.
insert into public.profiles(id, display_name, email, phone)
select id,
       coalesce(raw_user_meta_data->>'full_name', ''),
       coalesce(email, ''),
       coalesce(raw_user_meta_data->>'phone', phone, '')
from auth.users
on conflict (id) do update set
  display_name = case
    when public.profiles.display_name = '' then excluded.display_name
    else public.profiles.display_name
  end,
  email = excluded.email,
  phone = case
    when excluded.phone <> '' then excluded.phone
    else public.profiles.phone
  end;
