alter table public.profiles add column if not exists is_discoverable boolean not null default true;
create index if not exists profiles_discoverable_username_idx on public.profiles (lower(username)) where is_discoverable;

create or replace function public.search_public_profiles(p_query text, p_limit integer default 20)
returns table(id uuid, username text, display_name text, avatar_url text)
language plpgsql stable security definer set search_path = '' as $$
declare v_query text := lower(trim(leading '@' from trim(coalesce(p_query, ''))));
begin
  if (select auth.uid()) is null then raise exception 'authentication required' using errcode='42501'; end if;
  if char_length(v_query)<1 then return; end if;
  return query select p.id,p.username,p.display_name,p.avatar_url from public.profiles p
    where p.is_discoverable and p.id<>(select auth.uid())
      and (lower(p.username) like v_query||'%' or lower(p.display_name) like '%'||v_query||'%')
    order by (lower(p.username)=v_query) desc,(lower(p.username) like v_query||'%') desc,lower(p.username)
    limit least(greatest(coalesce(p_limit,20),1),20);
end $$;

create or replace function public.search_trip_candidates(p_trip_id uuid,p_query text)
returns table(id uuid,username text,display_name text,avatar_url text,relationship text)
language plpgsql stable security definer set search_path='' as $$
declare v_query text:=lower(trim(leading '@' from trim(coalesce(p_query,''))));
begin
  if not private.is_trip_admin(p_trip_id) then raise exception 'trip administrator permission required' using errcode='42501'; end if;
  return query select p.id,p.username,p.display_name,p.avatar_url,
    case when m.user_id is not null then 'member' when i.id is not null then 'invited' else 'invite' end
    from public.profiles p
    left join public.trip_members m on m.trip_id=p_trip_id and m.user_id=p.id
    left join public.trip_invites i on i.trip_id=p_trip_id and i.invited_user_id=p.id and i.status='pending'
    where p.id<>(select auth.uid()) and (p.is_discoverable or m.user_id is not null or i.id is not null)
      and (lower(p.username) like v_query||'%' or lower(p.display_name) like '%'||v_query||'%')
    order by (lower(p.username)=v_query) desc,lower(p.username) limit 20;
end $$;

revoke all on function public.search_public_profiles(text,integer),public.search_trip_candidates(uuid,text) from public,anon;
grant execute on function public.search_public_profiles(text,integer),public.search_trip_candidates(uuid,text) to authenticated;
