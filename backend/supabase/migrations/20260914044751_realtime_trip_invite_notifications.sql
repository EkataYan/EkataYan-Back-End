-- Deliver pending trip invitations through the same durable notifications
-- stream used by the rest of the application. The invitation remains the
-- source of truth for accepting/declining; payload stores only its relation.
create or replace function private.notify_trip_invite_created()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.notifications(user_id, trip_id, type, title, body, payload)
  select
    new.invited_user_id,
    new.trip_id,
    'trip_invite',
    'Trip invitation',
    coalesce(nullif(p.display_name, ''), '@' || p.username) ||
      ' invited you to join ' || t.name,
    jsonb_build_object(
      'trip_id', new.trip_id,
      'invite_id', new.id,
      'invited_by', new.invited_by
    )
  from public.trips t
  join public.profiles p on p.id = new.invited_by
  where t.id = new.trip_id;

  return new;
end
$$;

revoke all on function private.notify_trip_invite_created()
  from public, anon, authenticated;

drop trigger if exists trip_invite_created_notification on public.trip_invites;
create trigger trip_invite_created_notification
after insert on public.trip_invites
for each row execute function private.notify_trip_invite_created();

create or replace function private.mark_trip_invite_notification_resolved()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if old.status = 'pending'::public.trip_invite_status
     and new.status <> 'pending'::public.trip_invite_status then
    update public.notifications
    set read_at = coalesce(read_at, now())
    where user_id = new.invited_user_id
      and type = 'trip_invite'
      and payload ->> 'invite_id' = new.id::text;
  end if;
  return new;
end
$$;

revoke all on function private.mark_trip_invite_notification_resolved()
  from public, anon, authenticated;

drop trigger if exists trip_invite_resolved_notification on public.trip_invites;
create trigger trip_invite_resolved_notification
after update of status on public.trip_invites
for each row execute function private.mark_trip_invite_notification_resolved();

-- A pending invite is unique, so one durable notification per invite is
-- sufficient and protects against accidental trigger replays.
create unique index if not exists notifications_trip_invite_unique_idx
on public.notifications ((payload ->> 'invite_id'))
where type = 'trip_invite' and payload ? 'invite_id';

-- Realtime applies this RLS policy to each subscriber. Clients additionally
-- subscribe with user_id=eq.<authenticated-user>, so unrelated rows never
-- leave Supabase.
alter table public.notifications enable row level security;

drop policy if exists notifications_own on public.notifications;
create policy notifications_own
on public.notifications
for select
to authenticated
using ((select auth.uid()) = user_id);

drop policy if exists notifications_read on public.notifications;
create policy notifications_read
on public.notifications
for update
to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);

grant select on public.notifications to authenticated;
grant update(read_at) on public.notifications to authenticated;

-- Postgres Changes only emits tables that are in the supabase_realtime
-- publication. Keep this idempotent for projects where it was enabled by hand.
do $$
begin
  if not exists (
    select 1
    from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'notifications'
  ) then
    execute 'alter publication supabase_realtime add table public.notifications';
  end if;
end
$$;
