-- Memory sync table + RLS. ONLY wxvjajecvklfjxppawdx (never nexkymqahpkvzzlvivfi).
-- Approved by Joseph 2026-11-08 7:43 AM ET; applied as migration simko_memory_sync_rls.
-- Public anon key is insufficient: require an authenticated user JWT.
create table if not exists public.simko_memory_sync (
  owner_id uuid not null references auth.users(id),
  id text not null,
  local_user text not null,
  payload jsonb not null,
  primary key (owner_id, id)
);
alter table public.simko_memory_sync enable row level security;
drop policy if exists memory_select_self on public.simko_memory_sync;
drop policy if exists memory_insert_self on public.simko_memory_sync;
create policy memory_select_self on public.simko_memory_sync for select to authenticated using (owner_id = (select auth.uid()));
create policy memory_insert_self on public.simko_memory_sync for insert to authenticated with check (owner_id = (select auth.uid()));
-- Append-only: no UPDATE or DELETE grant or policy. Neither JWT user_metadata nor service_role is used.
revoke all on public.simko_memory_sync from anon;
revoke all on public.simko_memory_sync from authenticated;
grant select, insert on public.simko_memory_sync to authenticated;
