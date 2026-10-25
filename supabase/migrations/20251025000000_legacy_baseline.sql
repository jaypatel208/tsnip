-- The tables Tsnip v1 created by hand in the dashboard, so a fresh database
-- (supabase db reset) matches production. `if not exists` makes this a
-- no-op on production, where they already exist. Dropped by the contract
-- migration in supabase/pending/.

create table if not exists public.ts_db (
  id uuid primary key default gen_random_uuid(),
  chat_id text,
  channel_id text,
  user_name text,
  message text,
  delay integer,
  user_timestamp timestamptz,
  created_at timestamptz default now()
);

create table if not exists public.yt_db (
  id uuid primary key default gen_random_uuid(),
  chat_id text,
  video_id text,
  title text,
  status text,
  url text,
  channel text,
  channel_id text,
  marked boolean default false,
  stream_start_time timestamp
);

create table if not exists public.yt_channel_db (
  id uuid primary key default gen_random_uuid(),
  channel_id text,
  channel_name text,
  channel_template text,
  dc_channel_id text
);

create table if not exists public.blacklist_yt_channel (
  id uuid primary key default gen_random_uuid(),
  channel_id text
);
