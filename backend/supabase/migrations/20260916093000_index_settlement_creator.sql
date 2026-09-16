-- Cover the remaining settlement foreign key for efficient user deletion checks.
create index settlements_created_by_idx on public.settlements(created_by, trip_id);
