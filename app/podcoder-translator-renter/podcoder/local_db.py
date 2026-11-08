#!/usr/bin/env python3
"""SQLite mirror for jobs, routines, memories, and approvals. No network."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

_LOCK = threading.Lock()

SCHEMA = """
create table if not exists jobs (
  id text primary key,
  user_id text not null,
  kind text not null,
  status text not null,
  payload text not null,
  result text not null default '',
  error text not null default '',
  attempts integer not null default 0,
  max_attempts integer not null default 3,
  created_at text not null,
  updated_at text not null
);
create table if not exists job_logs (
  id integer primary key autoincrement,
  job_id text not null,
  at text not null,
  line text not null
);
create table if not exists routines (
  id text primary key,
  user_id text not null,
  name text not null,
  kind text not null,
  spec text not null,
  last_run text not null default '',
  created_at text not null
);
create table if not exists memories (
  id text primary key,
  user_id text not null,
  text text not null,
  type text not null,
  categories text not null,
  source_session text not null default '',
  created_at text not null
);
create table if not exists approvals (
  id text primary key,
  job_id text not null,
  action text not null,
  summary text not null,
  status text not null,
  created_at text not null
);
create table if not exists transcripts (
  id text primary key,
  user_id text not null,
  title text not null,
  creator text not null default '',
  url text not null default '',
  speakers text not null default '[]',
  categories text not null default '[]',
  tags text not null default '[]',
  created_at text not null
);
create table if not exists transcript_segments (
  id text primary key,
  transcript_id text not null,
  speaker text not null default '',
  start_ms integer not null,
  end_ms integer not null,
  text text not null
);
create table if not exists humor_bits (
  id text primary key,
  text text not null,
  tags text not null,
  category text not null default '',
  tone text not null default '',
  clean integer not null default 1,
  sample integer not null default 0,
  created_at text not null
);
"""


def connect(state: Path) -> sqlite3.Connection:
    state.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(state / "podcoder.sqlite")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def lock():
    return _LOCK
