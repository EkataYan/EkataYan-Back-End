-- Keep invitation response and membership insertion in one transaction while
-- assigning values with the column's enum type (Postgres 42804 follow-up).
create or replace function public.respond_trip_invite(p_invite_id uuid, p_accept boolean)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_invite public.trip_invites%rowtype;
begin
  select * into v_invite
  from public.trip_invites
  where id = p_invite_id
  for update;

  if not found then
    raise exception 'invitation not found' using errcode = 'P0002';
  end if;
  if v_invite.invited_user_id <> (select auth.uid()) then
    raise exception 'invitation does not belong to user' using errcode = '42501';
  end if;
  if v_invite.status <> 'pending'::public.trip_invite_status then
    raise exception 'invitation is no longer pending' using errcode = '22023';
  end if;

  if p_accept then
    insert into public.trip_members (trip_id, user_id, role)
    values (v_invite.trip_id, (select auth.uid()), 'member'::public.trip_role)
    on conflict (trip_id, user_id) do nothing;
  end if;

  update public.trip_invites
  set status = case
      when p_accept then 'accepted'::public.trip_invite_status
      else 'declined'::public.trip_invite_status
    end,
    responded_at = now()
  where id = p_invite_id
  returning * into v_invite;

  return to_jsonb(v_invite);
end
$$;

revoke all on function public.respond_trip_invite(uuid, boolean) from public, anon;
grant execute on function public.respond_trip_invite(uuid, boolean) to authenticated;
