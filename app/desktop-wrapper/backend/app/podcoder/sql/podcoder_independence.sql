-- Independence tables for project wxvjajecvklfjxppawdx.
-- https://wxvjajecvklfjxppawdx.supabase.co
-- Do not apply this file to nexkymqahpkvzzlvivfi.
-- The pack does not run this SQL. Lifebook values stay words.

create table if not exists podcoder_jobs (
  id text primary key,
  user_id text not null,
  kind text not null,
  status text not null,
  created_at timestamptz not null default now()
);

create table if not exists podcoder_memories (
  id text primary key,
  user_id text not null,
  text text not null,
  type text not null check (type in ('fact', 'preference', 'goal', 'event')),
  categories text[] not null default '{}',
  source_session text,
  created_at timestamptz not null default now()
);

create table if not exists podcoder_transcripts (
  id text primary key,
  user_id text not null,
  title text not null,
  creator text not null default '',
  url text not null default '',
  speakers text[] not null default '{}',
  categories text[] not null default '{}',
  tags text[] not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists podcoder_transcript_segments (
  id text primary key,
  transcript_id text not null references podcoder_transcripts (id),
  speaker text not null default '',
  start_ms integer not null,
  end_ms integer not null,
  text text not null
);

create table if not exists podcoder_humor (
  id text primary key,
  text text not null,
  tags text[] not null default '{}',
  category text not null default '',
  tone text not null default '',
  clean boolean not null default true,
  sample boolean not null default false,
  created_at timestamptz not null default now()
);
