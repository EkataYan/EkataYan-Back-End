-- Preserve the complete redesigned AI Planner contract while retaining the relational graph
-- consumed by existing Trips clients.
alter table public.trips
  add column if not exists planner_context jsonb not null default '{}'::jsonb;

alter table public.itineraries
  add column if not exists structured_data jsonb not null default '{}'::jsonb;

create or replace function public.save_itinerary(p_trip_id uuid, p_data jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_itinerary uuid := gen_random_uuid(); v_day jsonb; v_activity jsonb; v_day_id uuid; v_position smallint;
begin
  if not private.is_trip_admin(p_trip_id) then raise exception 'not allowed' using errcode='42501'; end if;
  insert into public.itineraries(id,trip_id,overview,currency,recommendations,structured_data,generated_by)
  values(v_itinerary,p_trip_id,p_data->>'overview',p_data->>'currency',
    array(select jsonb_array_elements_text(coalesce(p_data->'recommendations','[]'))),
    coalesce(p_data->'structured_data','{}'::jsonb),(select auth.uid()));
  for v_day in select * from jsonb_array_elements(p_data->'days') loop
    insert into public.itinerary_days(itinerary_id,day_number,trip_date,locations,notes)
    values(v_itinerary,(v_day->>'day_number')::smallint,(v_day->>'date')::date,
      array(select jsonb_array_elements_text(v_day->'locations')),coalesce(v_day->>'notes','')) returning id into v_day_id;
    v_position := 0;
    for v_activity in select * from jsonb_array_elements(v_day->'activities') loop
      v_position := v_position+1;
      insert into public.itinerary_activities(itinerary_day_id,position,title,location,suggested_time,
        description,estimated_cost,transport,notes,external_place_id,latitude,longitude,category)
      values(v_day_id,v_position,v_activity->>'title',v_activity->>'location',
        (v_activity->>'suggested_time')::time,v_activity->>'description',
        (v_activity->>'estimated_cost')::numeric(14,2),coalesce(v_activity->>'transport',''),
        coalesce(v_activity->>'notes',''),nullif(v_activity->>'external_place_id',''),
        nullif(v_activity->>'latitude','')::numeric(9,6),nullif(v_activity->>'longitude','')::numeric(9,6),
        coalesce(nullif(v_activity->>'category',''),'other'));
    end loop;
  end loop;
  return (select to_jsonb(i) from public.itineraries i where i.id=v_itinerary);
end $$;

revoke all on function public.save_itinerary(uuid,jsonb) from public, anon;
grant execute on function public.save_itinerary(uuid,jsonb) to authenticated;
