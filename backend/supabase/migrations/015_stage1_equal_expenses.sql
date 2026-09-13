-- Stage 1 uses the existing expenses + expense_participants schema.
-- Monetary shares are calculated inside one short database transaction so an
-- expense can never exist without its complete split rows.
create or replace function public.create_equal_expense(p_trip_id uuid, p_data jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_id uuid := gen_random_uuid();
  v_amount numeric(14,2) := (p_data->>'amount')::numeric(14,2);
  v_paid_by uuid := (p_data->>'paid_by')::uuid;
  v_participants uuid[] := array(select jsonb_array_elements_text(p_data->'participant_ids')::uuid);
  v_count integer;
  v_base numeric(14,2);
  v_remainder integer;
begin
  if (select auth.uid()) is null or not private.is_trip_member(p_trip_id) then
    raise exception 'trip membership required' using errcode='42501';
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

  insert into public.expenses(id,trip_id,title,description,amount,currency,category,paid_by,split_type,incurred_at,created_by)
  values(v_id,p_trip_id,p_data->>'title',coalesce(p_data->>'notes',''),v_amount,'LKR',p_data->>'category',
    v_paid_by,'equal'::public.expense_split_type,(p_data->>'expense_date')::date::timestamptz,(select auth.uid()));

  v_base := trunc(v_amount/v_count,2);
  v_remainder := ((v_amount-v_base*v_count)*100)::integer;
  insert into public.expense_participants(expense_id,user_id,share)
  select v_id,user_id,v_base + case when row_number() over(order by user_id) <= v_remainder then 0.01 else 0 end
  from unnest(v_participants) user_id;

  return (select jsonb_build_object(
    'id',e.id,'trip_id',e.trip_id,'title',e.title,'amount',e.amount::text,'currency',e.currency,
    'category',e.category,'expense_date',e.incurred_at::date,'notes',e.description,
    'paid_by',e.paid_by,'created_by',e.created_by,'created_at',e.created_at,'split_type',e.split_type,
    'payer',jsonb_build_object('id',payer.id,'display_name',payer.display_name,'username',payer.username,'avatar_url',payer.avatar_url),
    'participants',(select coalesce(jsonb_agg(jsonb_build_object('user_id',ep.user_id,'display_name',p.display_name,
      'username',p.username,'avatar_url',p.avatar_url,'share_amount',ep.share::text) order by p.display_name),'[]'::jsonb)
      from public.expense_participants ep join public.profiles p on p.id=ep.user_id where ep.expense_id=e.id)
  ) from public.expenses e join public.profiles payer on payer.id=e.paid_by where e.id=v_id);
end $$;

create or replace function public.list_trip_expenses_public(p_trip_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if not private.is_trip_member(p_trip_id) then raise exception 'trip membership required' using errcode='42501'; end if;
  return (select coalesce(jsonb_agg(item order by incurred_at desc,created_at desc),'[]'::jsonb) from (
    select e.incurred_at,e.created_at,jsonb_build_object(
      'id',e.id,'trip_id',e.trip_id,'title',e.title,'amount',e.amount::text,'currency',e.currency,
      'category',e.category,'expense_date',e.incurred_at::date,'notes',e.description,
      'paid_by',e.paid_by,'created_by',e.created_by,'created_at',e.created_at,'split_type',e.split_type,
      'payer',jsonb_build_object('id',payer.id,'display_name',payer.display_name,'username',payer.username,'avatar_url',payer.avatar_url),
      'participants',(select coalesce(jsonb_agg(jsonb_build_object('user_id',ep.user_id,'display_name',p.display_name,
        'username',p.username,'avatar_url',p.avatar_url,'share_amount',ep.share::text) order by p.display_name),'[]'::jsonb)
        from public.expense_participants ep join public.profiles p on p.id=ep.user_id where ep.expense_id=e.id)
    ) item from public.expenses e join public.profiles payer on payer.id=e.paid_by where e.trip_id=p_trip_id
  ) rows);
end $$;

create or replace function public.get_trip_expense_balances(p_trip_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if not private.is_trip_member(p_trip_id) then raise exception 'trip membership required' using errcode='42501'; end if;
  return jsonb_build_object('trip_id',p_trip_id,'balances',(select coalesce(jsonb_agg(jsonb_build_object(
    'user_id',m.user_id,'display_name',p.display_name,'username',p.username,'avatar_url',p.avatar_url,
    'amount_paid',coalesce(paid.amount,0)::numeric(14,2)::text,
    'amount_owed',coalesce(owed.amount,0)::numeric(14,2)::text,
    'net_balance',(coalesce(paid.amount,0)-coalesce(owed.amount,0))::numeric(14,2)::text
  ) order by p.display_name),'[]'::jsonb)
  from public.trip_members m join public.profiles p on p.id=m.user_id
  left join (select paid_by,sum(amount) amount from public.expenses where trip_id=p_trip_id group by paid_by) paid on paid.paid_by=m.user_id
  left join (select ep.user_id,sum(ep.share) amount from public.expense_participants ep join public.expenses e on e.id=ep.expense_id
    where e.trip_id=p_trip_id group by ep.user_id) owed on owed.user_id=m.user_id
  where m.trip_id=p_trip_id));
end $$;

revoke all on function public.create_equal_expense(uuid,jsonb), public.list_trip_expenses_public(uuid),
  public.get_trip_expense_balances(uuid) from public,anon;
grant execute on function public.create_equal_expense(uuid,jsonb), public.list_trip_expenses_public(uuid),
  public.get_trip_expense_balances(uuid) to authenticated;
