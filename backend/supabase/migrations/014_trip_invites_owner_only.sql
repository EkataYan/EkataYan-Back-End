-- Only the trip creator/owner may discover invite candidates or send invites.
-- Flask also checks this, while these SECURITY DEFINER functions remain the
-- authoritative database boundary for direct RPC calls using a user JWT.
create or replace function public.create_trip_invite(p_trip_id uuid, p_invited_user_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare v_invite public.trip_invites%rowtype;
begin
  if (select auth.uid()) is null then raise exception 'authentication required' using errcode='42501'; end if;
  if not private.is_trip_owner(p_trip_id) then raise exception 'trip owner permission required' using errcode='42501'; end if;
  if p_invited_user_id = (select auth.uid()) then raise exception 'cannot invite yourself' using errcode='22023'; end if;
  if not exists(select 1 from public.profiles where id=p_invited_user_id) then raise exception 'user not found' using errcode='P0002'; end if;
  if exists(select 1 from public.trip_members where trip_id=p_trip_id and user_id=p_invited_user_id) then raise exception 'already a trip member' using errcode='23505'; end if;
  if exists(select 1 from public.trip_invites where trip_id=p_trip_id and invited_user_id=p_invited_user_id and status='pending') then raise exception 'invitation already pending' using errcode='23505'; end if;
  insert into public.trip_invites(trip_id,invited_user_id,invited_by)
    values(p_trip_id,p_invited_user_id,(select auth.uid())) returning * into v_invite;
  return to_jsonb(v_invite);
end $$;

create or replace function public.search_trip_candidates(p_trip_id uuid, p_query text)
returns table(id uuid, username text, display_name text, avatar_url text, relationship text)
language plpgsql stable security definer set search_path = '' as $$
declare v_query text:=lower(trim(leading '@' from trim(coalesce(p_query,''))));
begin
  if not private.is_trip_owner(p_trip_id) then raise exception 'trip owner permission required' using errcode='42501'; end if;
  return query select p.id,p.username,p.display_name,p.avatar_url,
    case when m.user_id is not null then 'member' when i.id is not null then 'invited' else 'invite' end
    from public.profiles p
    left join public.trip_members m on m.trip_id=p_trip_id and m.user_id=p.id
    left join public.trip_invites i on i.trip_id=p_trip_id and i.invited_user_id=p.id and i.status='pending'
    where p.id<>(select auth.uid()) and (lower(p.username) like v_query||'%' or lower(p.display_name) like '%'||v_query||'%')
    order by (lower(p.username)=v_query) desc,lower(p.username) limit 20;
end $$;

revoke all on function public.create_trip_invite(uuid,uuid), public.search_trip_candidates(uuid,text) from public,anon;
grant execute on function public.create_trip_invite(uuid,uuid), public.search_trip_candidates(uuid,text) to authenticated;
