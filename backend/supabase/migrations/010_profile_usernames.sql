-- Add public, searchable usernames to the existing auth-linked profile model.
alter table public.profiles
  add column if not exists username text,
  add column if not exists avatar_url text;

create or replace function public.generate_unique_username(p_display_name text)
returns text
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_base text;
  v_candidate text;
  v_attempt integer := 0;
begin
  v_base := lower(regexp_replace(coalesce(p_display_name, ''), '[^a-zA-Z0-9]', '', 'g'));
  if char_length(v_base) < 1 then v_base := 'user'; end if;
  v_base := left(v_base, 14);
  loop
    v_candidate := v_base || lpad(floor(random() * 1000000)::integer::text, 6, '0');
    exit when not exists (select 1 from public.profiles p where lower(p.username) = v_candidate);
    v_attempt := v_attempt + 1;
    if v_attempt >= 25 then raise exception 'unable to allocate username'; end if;
  end loop;
  return v_candidate;
end;
$$;

update public.profiles
set username = public.generate_unique_username(display_name)
where username is null or username = '';

alter table public.profiles
  alter column username set not null,
  add constraint profiles_username_format check (username ~ '^[a-z0-9_]{3,20}$');

create unique index if not exists profiles_username_lower_uidx
  on public.profiles (lower(username));
create index if not exists profiles_display_name_lower_idx
  on public.profiles (lower(display_name) text_pattern_ops);

create or replace function public.create_profile() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_display_name text := coalesce(new.raw_user_meta_data->>'full_name', '');
begin
  insert into public.profiles(id, display_name, username, email, phone, avatar_url)
  values (
    new.id,
    v_display_name,
    public.generate_unique_username(v_display_name),
    coalesce(new.email, ''),
    coalesce(new.raw_user_meta_data->>'phone', new.phone, ''),
    nullif(coalesce(new.raw_user_meta_data->>'avatar_url', new.raw_user_meta_data->>'picture', ''), '')
  )
  on conflict (id) do update set
    display_name = excluded.display_name,
    email = excluded.email,
    phone = excluded.phone,
    avatar_url = coalesce(public.profiles.avatar_url, excluded.avatar_url),
    username = coalesce(public.profiles.username, excluded.username);
  raise log 'profile provisioned for auth user %', new.id;
  return new;
end $$;

create or replace function public.search_public_profiles(p_query text, p_limit integer default 20)
returns table(id uuid, username text, display_name text, avatar_url text)
language plpgsql stable security definer set search_path = '' as $$
declare v_query text := lower(trim(leading '@' from trim(coalesce(p_query, ''))));
begin
  if (select auth.uid()) is null then raise exception 'authentication required' using errcode = '42501'; end if;
  if char_length(v_query) < 1 then return; end if;
  return query
    select p.id, p.username, p.display_name, p.avatar_url
    from public.profiles p
    where lower(p.username) like v_query || '%'
       or lower(p.display_name) like '%' || v_query || '%'
    order by (lower(p.username) = v_query) desc,
             (lower(p.username) like v_query || '%') desc,
             lower(p.username)
    limit least(greatest(coalesce(p_limit, 20), 1), 20);
end $$;

create or replace function public.is_username_available(p_username text)
returns boolean language plpgsql stable security definer set search_path = '' as $$
declare v_username text := lower(trim(leading '@' from trim(coalesce(p_username, ''))));
begin
  if (select auth.uid()) is null then raise exception 'authentication required' using errcode = '42501'; end if;
  if v_username !~ '^[a-z0-9_]{3,20}$' then return false; end if;
  return not exists (
    select 1 from public.profiles p
    where lower(p.username) = v_username and p.id <> (select auth.uid())
  );
end $$;

revoke all on function public.generate_unique_username(text) from public, anon, authenticated;
revoke all on function public.search_public_profiles(text, integer) from public, anon;
revoke all on function public.is_username_available(text) from public, anon;
grant execute on function public.search_public_profiles(text, integer), public.is_username_available(text) to authenticated;
