-- Trip totals can legitimately exceed the numeric(14,2) limit enforced for a
-- single expense. Keep the per-expense constraint, but do not narrow SUM()
-- aggregates back to that single-row type when serializing balances.
create or replace function public.get_trip_expense_balances(p_trip_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if not private.is_trip_member(p_trip_id) then
    raise exception 'trip membership required' using errcode='42501';
  end if;

  return jsonb_build_object(
    'trip_id', p_trip_id,
    'balances', (
      select coalesce(
        jsonb_agg(
          jsonb_build_object(
            'user_id', m.user_id,
            'display_name', p.display_name,
            'username', p.username,
            'avatar_url', p.avatar_url,
            'amount_paid', round(coalesce(paid.amount, 0), 2)::text,
            'amount_owed', round(coalesce(owed.amount, 0), 2)::text,
            'net_balance', round(coalesce(paid.amount, 0) - coalesce(owed.amount, 0), 2)::text
          ) order by p.display_name
        ),
        '[]'::jsonb
      )
      from public.trip_members m
      join public.profiles p on p.id = m.user_id
      left join (
        select paid_by, sum(amount) amount
        from public.expenses
        where trip_id = p_trip_id
        group by paid_by
      ) paid on paid.paid_by = m.user_id
      left join (
        select ep.user_id, sum(ep.share) amount
        from public.expense_participants ep
        join public.expenses e on e.id = ep.expense_id
        where e.trip_id = p_trip_id
        group by ep.user_id
      ) owed on owed.user_id = m.user_id
      where m.trip_id = p_trip_id
    )
  );
end $$;

revoke all on function public.get_trip_expense_balances(uuid) from public, anon;
grant execute on function public.get_trip_expense_balances(uuid) to authenticated;
