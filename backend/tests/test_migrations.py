from pathlib import Path


def test_expense_balance_totals_are_not_narrowed_to_single_expense_precision():
    migration = (
        Path(__file__).parents[1]
        / "supabase"
        / "migrations"
        / "20260915120000_fix_expense_balance_numeric_overflow.sql"
    ).read_text(encoding="utf-8")

    assert "round(coalesce(paid.amount, 0), 2)::text" in migration
    assert "round(coalesce(owed.amount, 0), 2)::text" in migration
    assert "::numeric(14,2)::text" not in migration.replace(" ", "")
    assert "security definer set search_path = ''" in migration
    assert "private.is_trip_member(p_trip_id)" in migration


def test_profile_table_reads_are_owner_only_and_public_fields_stay_in_rpcs():
    root = Path(__file__).parents[1]
    migration = (root / "supabase" / "migrations" / "20260915123000_restrict_profile_contact_visibility.sql").read_text(encoding="utf-8")
    invitation_rpc = (root / "supabase" / "migrations" / "016_profile_discoverability.sql").read_text(encoding="utf-8")

    assert "using (id = (select auth.uid()))" in migration
    assert "private.shares_trip_with" not in migration
    assert "returns table(id uuid, username text, display_name text, avatar_url text)" in invitation_rpc


def test_removing_saved_place_atomically_clears_matching_cover():
    migration = (
        Path(__file__).parents[1] / "supabase" / "migrations" /
        "20260915124500_clear_removed_wishlist_cover.sql"
    ).read_text(encoding="utf-8")

    assert "after delete on public.saved_places" in migration
    assert "cover_path = old.external_place_id" in migration
    assert "set search_path = ''" in migration


def test_completed_expenses_migration_is_additive_and_secured():
    migration = (Path(__file__).parents[1] / "supabase" / "migrations" /
                 "20260916090000_complete_expenses.sql").read_text(encoding="utf-8")
    assert "create table public.settlements" in migration
    assert "amount numeric(14,2)" in migration
    assert "alter table public.settlements enable row level security" in migration
    assert "private.is_trip_member(trip_id)" in migration
    assert "role='owner'" in migration
    assert "delete from public.expense_participants" in migration
    assert "private.trip_member_net" in migration
    assert "revoke all on function public.set_trip_budget" in migration
    assert "public.record_settlement(uuid,jsonb)" in migration
    assert "drop table" not in migration.lower()
