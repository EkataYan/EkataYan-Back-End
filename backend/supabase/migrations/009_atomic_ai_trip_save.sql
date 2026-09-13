-- Atomically persist an AI trip plus the exact structured itinerary reviewed by the user.
alter table public.trips
  add column if not exists source text not null default 'manual'
  check (source in ('manual', 'ai'));

create or replace function public.save_ai_trip(p_trip jsonb, p_itinerary jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_user_id uuid := (select auth.uid());
  v_trip public.trips%rowtype;
  v_saved_itinerary jsonb;
begin
  if v_user_id is null then
    raise exception 'authentication required' using errcode = '42501';
  end if;

  insert into public.trips(
    name, destinations, start_date, end_date, budget, currency, travelers,
    interests, preferred_activities, travel_style, accommodation_preference,
    transportation_preference, additional_requirements, status, planner_context,
    source, created_by
  ) values (
    p_trip->>'name',
    array(select jsonb_array_elements_text(p_trip->'destinations')),
    (p_trip->>'start_date')::date,
    (p_trip->>'end_date')::date,
    coalesce((p_trip->>'budget')::numeric, 0),
    coalesce(nullif(p_trip->>'currency', ''), 'LKR'),
    (p_trip->>'travelers')::smallint,
    array(select jsonb_array_elements_text(coalesce(p_trip->'interests', '[]'::jsonb))),
    array(select jsonb_array_elements_text(coalesce(p_trip->'preferred_activities', '[]'::jsonb))),
    coalesce(nullif(p_trip->>'travel_style', ''), 'Let AI decide'),
    coalesce(nullif(p_trip->>'accommodation_preference', ''), 'Let AI decide'),
    coalesce(nullif(p_trip->>'transportation_preference', ''), 'Let AI decide'),
    coalesce(p_trip->>'additional_requirements', ''),
    'planned',
    coalesce(p_trip->'planner_context', '{}'::jsonb),
    'ai',
    v_user_id
  ) returning * into v_trip;

  -- save_itinerary and all nested inserts execute in this same transaction.
  v_saved_itinerary := public.save_itinerary(v_trip.id, p_itinerary);

  return jsonb_build_object(
    'trip', to_jsonb(v_trip),
    'itinerary_id', v_saved_itinerary->>'id'
  );
end;
$$;

revoke all on function public.save_ai_trip(jsonb, jsonb) from public, anon;
grant execute on function public.save_ai_trip(jsonb, jsonb) to authenticated;
