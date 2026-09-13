-- Trip membership remains the single authority; invitations only govern joining.
create type public.trip_invite_status as enum ('pending', 'accepted', 'declined', 'cancelled');

create table public.trip_invites (
  id uuid primary key default gen_random_uuid(),
  trip_id uuid not null references public.trips(id) on delete cascade,
  invited_user_id uuid not null references auth.users(id) on delete cascade,
  invited_by uuid not null references auth.users(id) on delete restrict,
  status public.trip_invite_status not null default 'pending',
  created_at timestamptz not null default now(),
  responded_at timestamptz,
  check (invited_user_id <> invited_by)
);
create unique index trip_invites_one_pending_idx on public.trip_invites(trip_id, invited_user_id) where status = 'pending';
create index trip_invites_recipient_idx on public.trip_invites(invited_user_id, status, created_at desc);
create index trip_invites_trip_idx on public.trip_invites(trip_id, status);
alter table public.trip_invites enable row level security;

create policy trip_invites_recipient_read on public.trip_invites for select to authenticated
  using (invited_user_id = (select auth.uid()));
create policy trip_invites_admin_read on public.trip_invites for select to authenticated
  using ((select private.is_trip_admin(trip_id)));

grant select on public.trip_invites to authenticated;

insert into public.trip_members(trip_id, user_id, role)
select id, created_by, 'owner'::public.trip_role from public.trips
on conflict (trip_id, user_id) do update set role = 'owner' where public.trip_members.role <> 'owner';

create or replace function public.create_trip_invite(p_trip_id uuid, p_invited_user_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare v_invite public.trip_invites%rowtype;
begin
  if (select auth.uid()) is null then raise exception 'authentication required' using errcode='42501'; end if;
  if not private.is_trip_admin(p_trip_id) then raise exception 'trip administrator permission required' using errcode='42501'; end if;
  if p_invited_user_id = (select auth.uid()) then raise exception 'cannot invite yourself' using errcode='22023'; end if;
  if not exists(select 1 from public.profiles where id=p_invited_user_id) then raise exception 'user not found' using errcode='P0002'; end if;
  if exists(select 1 from public.trip_members where trip_id=p_trip_id and user_id=p_invited_user_id) then raise exception 'already a trip member' using errcode='23505'; end if;
  if exists(select 1 from public.trip_invites where trip_id=p_trip_id and invited_user_id=p_invited_user_id and status='pending') then raise exception 'invitation already pending' using errcode='23505'; end if;
  insert into public.trip_invites(trip_id,invited_user_id,invited_by)
    values(p_trip_id,p_invited_user_id,(select auth.uid())) returning * into v_invite;
  return to_jsonb(v_invite);
end $$;

create or replace function public.list_my_trip_invites()
returns table(invite_id uuid, trip_id uuid, trip_name text, trip_start_date date, trip_end_date date,
  inviter_id uuid, inviter_display_name text, inviter_username text, inviter_avatar_url text,
  status public.trip_invite_status, created_at timestamptz)
language sql stable security definer set search_path = '' as $$
  select i.id,i.trip_id,t.name,t.start_date,t.end_date,p.id,p.display_name,p.username,p.avatar_url,i.status,i.created_at
  from public.trip_invites i join public.trips t on t.id=i.trip_id join public.profiles p on p.id=i.invited_by
  where i.invited_user_id=(select auth.uid()) and i.status='pending'
  order by i.created_at desc
$$;

create or replace function public.respond_trip_invite(p_invite_id uuid, p_accept boolean)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare v_invite public.trip_invites%rowtype;
begin
  select * into v_invite from public.trip_invites where id=p_invite_id for update;
  if not found then raise exception 'invitation not found' using errcode='P0002'; end if;
  if v_invite.invited_user_id <> (select auth.uid()) then raise exception 'invitation does not belong to user' using errcode='42501'; end if;
  if v_invite.status <> 'pending' then raise exception 'invitation is no longer pending' using errcode='22023'; end if;
  if p_accept then
    insert into public.trip_members(trip_id,user_id,role) values(v_invite.trip_id,(select auth.uid()),'member')
      on conflict (trip_id,user_id) do nothing;
  end if;
  update public.trip_invites set status=case when p_accept then 'accepted' else 'declined' end,
    responded_at=now() where id=p_invite_id returning * into v_invite;
  return to_jsonb(v_invite);
end $$;

create or replace function public.list_trip_members_public(p_trip_id uuid)
returns table(user_id uuid, display_name text, username text, avatar_url text, role public.trip_role, joined_at timestamptz, is_current_user boolean)
language plpgsql stable security definer set search_path = '' as $$
begin
  if not private.is_trip_member(p_trip_id) then raise exception 'trip membership required' using errcode='42501'; end if;
  return query select m.user_id,p.display_name,p.username,p.avatar_url,m.role,m.joined_at,m.user_id=(select auth.uid())
    from public.trip_members m join public.profiles p on p.id=m.user_id
    where m.trip_id=p_trip_id order by case m.role when 'owner' then 0 when 'admin' then 1 else 2 end,p.display_name;
end $$;

create or replace function public.search_trip_candidates(p_trip_id uuid, p_query text)
returns table(id uuid, username text, display_name text, avatar_url text, relationship text)
language plpgsql stable security definer set search_path = '' as $$
declare v_query text:=lower(trim(leading '@' from trim(coalesce(p_query,''))));
begin
  if not private.is_trip_admin(p_trip_id) then raise exception 'trip administrator permission required' using errcode='42501'; end if;
  return query select p.id,p.username,p.display_name,p.avatar_url,
    case when m.user_id is not null then 'member' when i.id is not null then 'invited' else 'invite' end
    from public.profiles p
    left join public.trip_members m on m.trip_id=p_trip_id and m.user_id=p.id
    left join public.trip_invites i on i.trip_id=p_trip_id and i.invited_user_id=p.id and i.status='pending'
    where p.id<>(select auth.uid()) and (lower(p.username) like v_query||'%' or lower(p.display_name) like '%'||v_query||'%')
    order by (lower(p.username)=v_query) desc,lower(p.username) limit 20;
end $$;

create or replace function public.remove_trip_member(p_trip_id uuid,p_user_id uuid)
returns boolean language plpgsql security definer set search_path='' as $$
declare v_target_role public.trip_role;
begin
  if not private.is_trip_admin(p_trip_id) then raise exception 'trip administrator permission required' using errcode='42501'; end if;
  select role into v_target_role from public.trip_members where trip_id=p_trip_id and user_id=p_user_id;
  if v_target_role is null then raise exception 'member not found' using errcode='P0002'; end if;
  if v_target_role<>'member' or p_user_id=(select auth.uid()) then raise exception 'member cannot be removed' using errcode='42501'; end if;
  delete from public.trip_members where trip_id=p_trip_id and user_id=p_user_id; return true;
end $$;

create or replace function public.leave_trip(p_trip_id uuid)
returns boolean language plpgsql security definer set search_path='' as $$
declare v_role public.trip_role;
begin
  select role into v_role from public.trip_members where trip_id=p_trip_id and user_id=(select auth.uid());
  if v_role is null then raise exception 'not a trip member' using errcode='P0002'; end if;
  if v_role='owner' then raise exception 'owner must transfer ownership or delete the trip' using errcode='22023'; end if;
  delete from public.trip_members where trip_id=p_trip_id and user_id=(select auth.uid()); return true;
end $$;

revoke all on function public.create_trip_invite(uuid,uuid), public.list_my_trip_invites(), public.respond_trip_invite(uuid,boolean),
  public.list_trip_members_public(uuid), public.search_trip_candidates(uuid,text), public.remove_trip_member(uuid,uuid), public.leave_trip(uuid)
  from public,anon;
grant execute on function public.create_trip_invite(uuid,uuid), public.list_my_trip_invites(), public.respond_trip_invite(uuid,boolean),
  public.list_trip_members_public(uuid), public.search_trip_candidates(uuid,text), public.remove_trip_member(uuid,uuid), public.leave_trip(uuid)
  to authenticated;
