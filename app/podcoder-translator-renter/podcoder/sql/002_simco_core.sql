-- Simco SI core: metrics, memory entries, goals, timeline events, category scores,
-- findings, recommendations, evidence, feedback and bandit arms.
--
-- Target project: wxvjajecvklfjxppawdx  (https://wxvjajecvklfjxppawdx.supabase.co)
-- NEVER apply to nexkymqahpkvzzlvivfi.
-- FILE ONLY. Nothing in this pack runs it. Applying it needs Joseph's direct OK.
--
-- Display rule: Lifebook shows words up front; the 0-100 number is stored here
-- for the details view only.
-- RLS: every table on, policies `to authenticated` with (select auth.uid()) = user_id.
-- Views use security_invoker; the one security definer function pins search_path = ''.

begin;

create table if not exists public.simco_metrics_daily (
  user_id uuid not null references auth.users (id) on delete cascade,
  day date not null,
  metric_key text not null check (metric_key ~ '^[a-z_]{2,40}$'),
  value numeric,
  source text not null default 'manual',
  synthetic boolean not null default false,
  imported_at timestamptz not null default now(),
  primary key (user_id, day, metric_key)
);

create table if not exists public.simco_memory_entries (
  id text primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  day date not null,
  at timestamptz not null,
  session_id text not null default '',
  text text not null check (char_length(text) <= 4000),
  categories text[] not null default '{}',
  status text not null default 'in play' check (status in ('doing well', 'in play', 'strained')),
  type text not null default 'event' check (type in ('fact', 'preference', 'goal', 'event')),
  synthetic boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists simco_memory_entries_user_day on public.simco_memory_entries (user_id, day);

create table if not exists public.simco_goals (
  id text not null,
  user_id uuid not null references auth.users (id) on delete cascade,
  category text not null,
  title text not null,
  start_day date not null,
  end_day date not null check (end_day >= start_day),
  synthetic boolean not null default false,
  primary key (user_id, id)
);

create table if not exists public.simco_goal_progress (
  user_id uuid not null references auth.users (id) on delete cascade,
  goal_id text not null,
  day date not null,
  progress numeric not null check (progress >= 0 and progress <= 1),
  primary key (user_id, goal_id, day),
  foreign key (user_id, goal_id) references public.simco_goals (user_id, id) on delete cascade
);

create table if not exists public.simco_timeline_events (
  id text not null,
  user_id uuid not null references auth.users (id) on delete cascade,
  day date not null,
  end_day date not null,
  kind text not null check (kind in ('milestone', 'life_event', 'workout', 'gap')),
  category text not null default '',
  title text not null,
  detail text not null default '',
  synthetic boolean not null default false,
  primary key (user_id, id),
  check (end_day >= day)
);

create table if not exists public.simco_category_scores (
  user_id uuid not null references auth.users (id) on delete cascade,
  day date not null,
  category text not null,
  score_0_100 smallint check (score_0_100 between 0 and 100),
  label_word text not null check (label_word in ('Thriving', 'Growing', 'Steady', 'Needs care', 'Not discussed')),
  components jsonb not null default '{}'::jsonb,
  rubric text not null default 'lifebook-rubric-v1',
  computed_at timestamptz not null default now(),
  primary key (user_id, day, category)
);

create table if not exists public.simco_findings (
  id text not null,
  user_id uuid not null references auth.users (id) on delete cascade,
  computed_for date not null,
  predictor text not null,
  outcome text not null,
  lag_days smallint not null check (lag_days between 0 and 3),
  n integer not null,
  rho numeric not null,
  p numeric not null,
  q numeric not null,
  ci_low numeric not null,
  ci_high numeric not null,
  strength text not null check (strength in ('finding', 'early signal', 'no signal')),
  statement text not null,
  primary key (user_id, computed_for, id)
);

create table if not exists public.simco_recommendations (
  id text not null,
  user_id uuid not null references auth.users (id) on delete cascade,
  day date not null,
  template_id text not null,
  category text not null,
  text text not null,
  rank smallint not null check (rank between 1 and 3),
  effort text not null check (effort in ('low', 'medium', 'high')),
  measurement jsonb not null,
  status text not null default 'shown' check (status in ('shown', 'accepted', 'ignored', 'completed')),
  created_at timestamptz not null default now(),
  primary key (user_id, id),
  unique (user_id, day, rank)
);

create table if not exists public.simco_evidence_links (
  user_id uuid not null references auth.users (id) on delete cascade,
  rec_id text not null,
  kind text not null check (kind in ('finding', 'metric', 'memory', 'goal', 'category')),
  ref_id text not null,
  snippet text not null default '',
  primary key (user_id, rec_id, kind, ref_id),
  foreign key (user_id, rec_id) references public.simco_recommendations (user_id, id) on delete cascade
);

create table if not exists public.simco_rec_feedback (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  rec_id text not null,
  action text not null check (action in ('accept', 'ignore', 'complete')),
  reason text not null default '',
  created_at timestamptz not null default now(),
  foreign key (user_id, rec_id) references public.simco_recommendations (user_id, id) on delete cascade
);

create table if not exists public.simco_bandit_arms (
  user_id uuid not null references auth.users (id) on delete cascade,
  template_id text not null,
  alpha numeric not null default 1 check (alpha >= 1),
  beta numeric not null default 1 check (beta >= 1),
  updated_at timestamptz not null default now(),
  primary key (user_id, template_id)
);

create table if not exists public.simco_seed_manifest (
  user_id uuid not null references auth.users (id) on delete cascade primary key,
  planted_effects jsonb not null,
  created_at timestamptz not null default now()
);

-- Max 3 recommendations a day is enforced by rank between 1 and 3 + unique (user_id, day, rank).

-- Integrity: a recommendation must never be shown without evidence. Deferred constraint
-- trigger so the rec and its evidence rows can be inserted in one transaction.
create or replace function public.simco_rec_has_evidence()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if not exists (
    select 1 from public.simco_evidence_links e
    where e.user_id = new.user_id and e.rec_id = new.id
  ) then
    raise exception 'recommendation % has no evidence link', new.id;
  end if;
  return null;
end;
$$;
revoke all on function public.simco_rec_has_evidence() from public, anon, authenticated;

drop trigger if exists simco_rec_has_evidence on public.simco_recommendations;
create constraint trigger simco_rec_has_evidence
  after insert or update on public.simco_recommendations
  deferrable initially deferred
  for each row execute function public.simco_rec_has_evidence();

-- Row level security on every table.
do $$
declare t text;
begin
  foreach t in array array[
    'simco_metrics_daily', 'simco_memory_entries', 'simco_goals', 'simco_goal_progress',
    'simco_timeline_events', 'simco_category_scores', 'simco_findings', 'simco_recommendations',
    'simco_evidence_links', 'simco_rec_feedback', 'simco_bandit_arms', 'simco_seed_manifest'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I on public.%I', t || '_owner_select', t);
    execute format('drop policy if exists %I on public.%I', t || '_owner_insert', t);
    execute format('drop policy if exists %I on public.%I', t || '_owner_update', t);
    execute format('drop policy if exists %I on public.%I', t || '_owner_delete', t);
    execute format('create policy %I on public.%I for select to authenticated using ((select auth.uid()) = user_id)', t || '_owner_select', t);
    execute format('create policy %I on public.%I for insert to authenticated with check ((select auth.uid()) = user_id)', t || '_owner_insert', t);
    execute format('create policy %I on public.%I for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id)', t || '_owner_update', t);
    execute format('create policy %I on public.%I for delete to authenticated using ((select auth.uid()) = user_id)', t || '_owner_delete', t);
  end loop;
end;
$$;

-- Feedback is append-only for users: no update/delete of past votes.
drop policy if exists simco_rec_feedback_owner_update on public.simco_rec_feedback;
drop policy if exists simco_rec_feedback_owner_delete on public.simco_rec_feedback;

-- Words-only view for the default (non-details) UI. security_invoker keeps RLS in force.
create or replace view public.simco_category_words
with (security_invoker = true) as
  select user_id, day, category, label_word
  from public.simco_category_scores;

commit;
