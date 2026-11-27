-- PodCoder cache shape for project wxvjajecvklfjxppawdx.
-- https://wxvjajecvklfjxppawdx.supabase.co
-- Do not apply this file to nexkymqahpkvzzlvivfi (Artemis/Omega).
-- The pack does not run this SQL. Status is a word, not a number.

create table if not exists podcoder_accounts (
  email text primary key,
  password_hash text not null,
  salt text not null,
  created_at timestamptz not null default now()
);

create table if not exists podcoder_sessions (
  id text primary key,
  account_email text not null references podcoder_accounts (email),
  title text not null default 'chat',
  created_at timestamptz not null default now()
);

create table if not exists podcoder_session_messages (
  id text primary key,
  session_id text not null references podcoder_sessions (id),
  role text not null,
  body text not null,
  created_at timestamptz not null default now()
);

create table if not exists podcoder_lifebook_tags (
  id bigint generated always as identity primary key,
  account_email text not null,
  category text not null check (category in (
    'health_fitness',
    'intellectual_life',
    'emotional_life',
    'character',
    'spiritual_life',
    'love_relationship',
    'parenting',
    'social_life',
    'financial_life',
    'career',
    'quality_of_life',
    'life_vision',
    'sex_and_sensuality'
  )),
  text_excerpt text not null,
  session_id text,
  status text not null default 'not discussed',
  created_at timestamptz not null default now()
);

create table if not exists podcoder_lifebook_dominance (
  id bigint generated always as identity primary key,
  account_email text not null,
  category text not null,
  note text not null,
  created_at timestamptz not null default now()
);

create table if not exists podcoder_sync_queue (
  id bigint generated always as identity primary key,
  table_name text not null,
  payload jsonb not null,
  created_at timestamptz not null default now()
);
