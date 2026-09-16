-- Complete the trip expense ledger without replacing existing expense data.
-- Zero was previously used by clients for "not set"; budget is now genuinely optional.
update public.trips set budget = null where budget = 0;
alter table public.trips alter column budget drop not null;
alter table public.trips drop constraint if exists trips_budget_check;
alter table public.trips add constraint trips_budget_positive check (budget is null or budget > 0);

create table public.settlements (
  id uuid primary key default gen_random_uuid(),
  trip_id uuid not null references public.trips(id) on delete cascade,
  paid_by uuid not null references auth.users(id) on delete restrict,
  paid_to uuid not null references auth.users(id) on delete restrict,
  amount numeric(14,2) not null check (amount > 0),
  payment_method text not null check (payment_method in ('Cash','Bank Transfer','Other')),
  note text not null default '' check (char_length(note) <= 1000),
  created_by uuid not null references auth.users(id) on delete restrict,
  settled_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint settlements_distinct_people check (paid_by <> paid_to)
);

create index settlements_trip_time_idx on public.settlements(trip_id, settled_at desc, id desc);
create index settlements_paid_by_idx on public.settlements(paid_by, trip_id);
create index settlements_paid_to_idx on public.settlements(paid_to, trip_id);

alter table public.settlements enable row level security;
create policy settlements_trip_member_read on public.settlements for select to authenticated
using ((select private.is_trip_member(trip_id)));
grant select on public.settlements to authenticated;

create or replace function public.set_trip_budget(p_trip_id uuid, p_budget_amount numeric)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare v_role public.trip_role; v_budget numeric(14,2);
begin
  if (select auth.uid()) is null then raise exception 'authentication required' using errcode='42501'; end if;
  select role into v_role from public.trip_members where trip_id=p_trip_id and user_id=(select auth.uid());
  if coalesce(v_role::text,'') not in ('owner','admin') then
    raise exception 'trip administrator permission required' using errcode='42501';
  end if;
  v_budget := round(p_budget_amount,2);
  if v_budget <= 0 then raise exception 'budget must be positive' using errcode='22023'; end if;
  update public.trips set budget=v_budget where id=p_trip_id;
  if not found then raise exception 'trip not found' using errcode='P0002'; end if;
  return jsonb_build_object('trip_id',p_trip_id,'budget_amount',v_budget::text,'currency','LKR');
end $$;

create or replace function private.expense_public_json(p_expense_id uuid)
returns jsonb language sql stable security definer set search_path = '' as $$
  select jsonb_build_object(
    'id',e.id,'trip_id',e.trip_id,'title',e.title,'amount',e.amount::text,'currency',e.currency,
    'category',e.category,'expense_date',e.incurred_at::date,'notes',e.description,
    'paid_by',e.paid_by,'created_by',e.created_by,'created_at',e.created_at,'split_type',e.split_type,
    'payer',jsonb_build_object('id',payer.id,'display_name',payer.display_name,'username',payer.username,'avatar_url',payer.avatar_url),
    'participants',(select coalesce(jsonb_agg(jsonb_build_object('user_id',ep.user_id,'display_name',p.display_name,
      'username',p.username,'avatar_url',p.avatar_url,'share_amount',ep.share::text) order by p.display_name),'[]'::jsonb)
      from public.expense_participants ep join public.profiles p on p.id=ep.user_id where ep.expense_id=e.id)
  ) from public.expenses e join public.profiles payer on payer.id=e.paid_by where e.id=p_expense_id
$$;

create or replace function public.update_equal_expense(p_trip_id uuid, p_expense_id uuid, p_data jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_amount numeric(14,2) := (p_data->>'amount')::numeric(14,2);
  v_paid_by uuid := (p_data->>'paid_by')::uuid;
  v_participants uuid[] := array(select jsonb_array_elements_text(p_data->'participant_ids')::uuid);
  v_count integer; v_base numeric(14,2); v_remainder integer; v_creator uuid; v_role public.trip_role;
begin
  select created_by into v_creator from public.expenses where id=p_expense_id and trip_id=p_trip_id for update;
  if v_creator is null then raise exception 'expense not found' using errcode='P0002'; end if;
  select role into v_role from public.trip_members where trip_id=p_trip_id and user_id=(select auth.uid());
  if v_creator <> (select auth.uid()) and coalesce(v_role::text,'') not in ('owner','admin') then
    raise exception 'expense edit not allowed' using errcode='42501';
  end if;
  if v_amount <= 0 then raise exception 'amount must be positive' using errcode='22023'; end if;
  if not exists(select 1 from public.trip_members where trip_id=p_trip_id and user_id=v_paid_by) then
    raise exception 'payer must be a trip member' using errcode='22023';
  end if;
  v_count := coalesce(cardinality(v_participants),0);
  if v_count < 1 or v_count <> (select count(distinct x) from unnest(v_participants) x) then
    raise exception 'participants must be non-empty and unique' using errcode='22023';
  end if;
  if exists(select 1 from unnest(v_participants) x where not exists(
      select 1 from public.trip_members m where m.trip_id=p_trip_id and m.user_id=x)) then
    raise exception 'every participant must be a trip member' using errcode='22023';
  end if;

  update public.expenses set title=p_data->>'title', description=coalesce(p_data->>'notes',''), amount=v_amount,
    category=p_data->>'category', paid_by=v_paid_by, split_type='equal'::public.expense_split_type,
    incurred_at=(p_data->>'expense_date')::date::timestamptz where id=p_expense_id;
  delete from public.expense_participants where expense_id=p_expense_id;
  v_base := trunc(v_amount/v_count,2);
  v_remainder := ((v_amount-v_base*v_count)*100)::integer;
  insert into public.expense_participants(expense_id,user_id,share)
  select p_expense_id,user_id,v_base + case when row_number() over(order by user_id) <= v_remainder then 0.01 else 0 end
  from unnest(v_participants) user_id;
  return private.expense_public_json(p_expense_id);
end $$;

create or replace function public.delete_expense(p_trip_id uuid, p_expense_id uuid)
returns boolean language plpgsql security definer set search_path = '' as $$
begin
  if not exists(select 1 from public.trip_members where trip_id=p_trip_id and user_id=(select auth.uid()) and role='owner') then
    raise exception 'only the trip owner may delete expenses' using errcode='42501';
  end if;
  delete from public.expenses where id=p_expense_id and trip_id=p_trip_id;
  if not found then raise exception 'expense not found' using errcode='P0002'; end if;
  return true;
end $$;

create or replace function private.trip_member_net(p_trip_id uuid, p_user_id uuid)
returns numeric language sql stable security definer set search_path = '' as $$
  select round(
    coalesce((select sum(amount) from public.expenses where trip_id=p_trip_id and paid_by=p_user_id),0)
    - coalesce((select sum(ep.share) from public.expense_participants ep join public.expenses e on e.id=ep.expense_id
      where e.trip_id=p_trip_id and ep.user_id=p_user_id),0)
    + coalesce((select sum(amount) from public.settlements where trip_id=p_trip_id and paid_by=p_user_id),0)
    - coalesce((select sum(amount) from public.settlements where trip_id=p_trip_id and paid_to=p_user_id),0), 2)
$$;

create or replace function public.record_settlement(p_trip_id uuid, p_data jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_id uuid := gen_random_uuid(); v_paid_by uuid := (select auth.uid());
  v_paid_to uuid := (p_data->>'paid_to')::uuid; v_amount numeric(14,2) := (p_data->>'amount')::numeric(14,2);
  v_payer_net numeric; v_recipient_net numeric;
begin
  if v_paid_by is null or not private.is_trip_member(p_trip_id) then
    raise exception 'trip membership required' using errcode='42501';
  end if;
  if v_paid_to=v_paid_by or not exists(select 1 from public.trip_members where trip_id=p_trip_id and user_id=v_paid_to) then
    raise exception 'recipient must be another trip member' using errcode='22023';
  end if;
  v_payer_net := private.trip_member_net(p_trip_id,v_paid_by);
  v_recipient_net := private.trip_member_net(p_trip_id,v_paid_to);
  if v_payer_net >= 0 or v_recipient_net <= 0 or v_amount <= 0 or v_amount > least(-v_payer_net,v_recipient_net) then
    raise exception 'amount exceeds the applicable outstanding balance' using errcode='22023';
  end if;
  insert into public.settlements(id,trip_id,paid_by,paid_to,amount,payment_method,note,created_by)
  values(v_id,p_trip_id,v_paid_by,v_paid_to,v_amount,p_data->>'payment_method',coalesce(p_data->>'note',''),v_paid_by);
  return (select jsonb_build_object('id',s.id,'trip_id',s.trip_id,'paid_by',s.paid_by,'paid_to',s.paid_to,
    'amount',s.amount::text,'payment_method',s.payment_method,'note',s.note,'settled_at',s.settled_at,
    'payer',jsonb_build_object('id',payer.id,'display_name',payer.display_name,'username',payer.username,'avatar_url',payer.avatar_url),
    'recipient',jsonb_build_object('id',recipient.id,'display_name',recipient.display_name,'username',recipient.username,'avatar_url',recipient.avatar_url))
    from public.settlements s join public.profiles payer on payer.id=s.paid_by join public.profiles recipient on recipient.id=s.paid_to where s.id=v_id);
end $$;

create or replace function public.list_trip_settlements_public(p_trip_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if not private.is_trip_member(p_trip_id) then raise exception 'trip membership required' using errcode='42501'; end if;
  return (select coalesce(jsonb_agg(jsonb_build_object('id',s.id,'trip_id',s.trip_id,'paid_by',s.paid_by,'paid_to',s.paid_to,
    'amount',s.amount::text,'payment_method',s.payment_method,'note',s.note,'settled_at',s.settled_at,
    'payer',jsonb_build_object('id',payer.id,'display_name',payer.display_name,'username',payer.username,'avatar_url',payer.avatar_url),
    'recipient',jsonb_build_object('id',recipient.id,'display_name',recipient.display_name,'username',recipient.username,'avatar_url',recipient.avatar_url))
    order by s.settled_at desc,s.id desc),'[]'::jsonb)
    from public.settlements s join public.profiles payer on payer.id=s.paid_by join public.profiles recipient on recipient.id=s.paid_to
    where s.trip_id=p_trip_id);
end $$;

create or replace function public.get_trip_expense_balances(p_trip_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if not private.is_trip_member(p_trip_id) then raise exception 'trip membership required' using errcode='42501'; end if;
  return jsonb_build_object('trip_id',p_trip_id,'balances',(select coalesce(jsonb_agg(jsonb_build_object(
    'user_id',m.user_id,'display_name',p.display_name,'username',p.username,'avatar_url',p.avatar_url,
    'amount_paid',round(coalesce(paid.amount,0),2)::text,'amount_owed',round(coalesce(owed.amount,0),2)::text,
    'net_balance',private.trip_member_net(p_trip_id,m.user_id)::text) order by p.display_name),'[]'::jsonb)
    from public.trip_members m join public.profiles p on p.id=m.user_id
    left join (select paid_by,sum(amount) amount from public.expenses where trip_id=p_trip_id group by paid_by) paid on paid.paid_by=m.user_id
    left join (select ep.user_id,sum(ep.share) amount from public.expense_participants ep join public.expenses e on e.id=ep.expense_id
      where e.trip_id=p_trip_id group by ep.user_id) owed on owed.user_id=m.user_id where m.trip_id=p_trip_id));
end $$;

create or replace function private.notify_budget_threshold()
returns trigger language plpgsql security definer set search_path = '' as $$
declare v_trip_id uuid; v_budget numeric; v_spent numeric; v_level text; v_body text;
begin
  if tg_table_name='trips' then v_trip_id:=coalesce(new.id,old.id); else v_trip_id:=coalesce(new.trip_id,old.trip_id); end if;
  select budget into v_budget from public.trips where id=v_trip_id;
  if v_budget is null then if tg_op='DELETE' then return old; else return new; end if; end if;
  select coalesce(sum(amount),0) into v_spent from public.expenses where trip_id=v_trip_id;
  if v_spent > v_budget then v_level:='exceeded'; v_body:='Trip budget exceeded by LKR '||round(v_spent-v_budget,2)::text||'.';
  elsif v_spent >= v_budget then v_level:='reached'; v_body:='You have reached your trip budget.';
  elsif v_spent >= v_budget*.8 then v_level:='near'; v_body:='You are nearing your trip budget.';
  else if tg_op='DELETE' then return old; else return new; end if; end if;
  insert into public.notifications(user_id,trip_id,type,title,body,payload)
  select m.user_id,v_trip_id,'budget_warning','Trip budget update',v_body,jsonb_build_object('trip_id',v_trip_id,'budget_level',v_level)
  from public.trip_members m where m.trip_id=v_trip_id and not exists(
    select 1 from public.notifications n where n.user_id=m.user_id and n.trip_id=v_trip_id and n.type='budget_warning'
      and n.payload->>'budget_level'=v_level);
  if tg_op='DELETE' then return old; else return new; end if;
end $$;

drop trigger if exists expense_budget_warning on public.expenses;
create trigger expense_budget_warning after insert or update of amount or delete on public.expenses
for each row execute function private.notify_budget_threshold();
drop trigger if exists trip_budget_warning on public.trips;
create trigger trip_budget_warning after update of budget on public.trips
for each row execute function private.notify_budget_threshold();

create or replace function private.notify_settlement_created()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.notifications(user_id,trip_id,type,title,body,payload)
  values(new.paid_to,new.trip_id,'settlement_recorded','Payment recorded','A trip member recorded a payment to you.',
    jsonb_build_object('trip_id',new.trip_id,'settlement_id',new.id));
  return new;
end $$;
drop trigger if exists settlement_created_notification on public.settlements;
create trigger settlement_created_notification after insert on public.settlements
for each row execute function private.notify_settlement_created();

revoke all on function private.expense_public_json(uuid), private.trip_member_net(uuid,uuid),
  private.notify_budget_threshold(), private.notify_settlement_created() from public,anon,authenticated;
revoke all on function public.set_trip_budget(uuid,numeric), public.update_equal_expense(uuid,uuid,jsonb),
  public.delete_expense(uuid,uuid), public.record_settlement(uuid,jsonb), public.list_trip_settlements_public(uuid),
  public.get_trip_expense_balances(uuid) from public,anon;
grant execute on function public.set_trip_budget(uuid,numeric), public.update_equal_expense(uuid,uuid,jsonb),
  public.delete_expense(uuid,uuid), public.record_settlement(uuid,jsonb), public.list_trip_settlements_public(uuid),
  public.get_trip_expense_balances(uuid) to authenticated;
