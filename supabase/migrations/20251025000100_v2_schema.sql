-- Tsnip v2: normalized tables next to the legacy ones (expand step).
--
--   channels    one row per YouTube channel: its settings
--   streams     one row per video: who owns it, when it started, comment state
--   timestamps  one row per !ts, pointing at its stream
--
-- A stream's channel comes from YouTube, never from the request, and a
-- timestamp's stream is derived here from the chat id, so a timestamp can't
-- land on another stream (the bug fixed in 640c6a3).

-- A YouTube live chat id is base64 of a protobuf whose field 2 (tag 0x12,
-- length 11) holds the video id. The tag can't occur inside the ASCII
-- channel id before it, so the first match is the only one.
create or replace function public.video_id_from_chat(chat text)
returns text
language plpgsql
immutable
set search_path = ''
as $$
declare
  raw bytea;
  i int;
  vid text;
begin
  raw := decode(
    translate(chat, '-_', '+/') || repeat('=', (4 - length(chat) % 4) % 4),
    'base64'
  );
  i := position('\x120b'::bytea in raw);
  if i = 0 or length(raw) < i + 12 then
    return null;
  end if;
  vid := convert_from(substring(raw from i + 2 for 11), 'UTF8');
  return case when vid ~ '^[A-Za-z0-9_-]{11}$' then vid end;
exception when others then
  return null;
end
$$;

create table if not exists public.channels (
  channel_id text primary key check (channel_id ~ '^UC[A-Za-z0-9_-]{22}$'),
  title text,
  dc_channel_id text,
  comment_template text,
  blacklisted boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists public.streams (
  video_id text primary key check (video_id ~ '^[A-Za-z0-9_-]{11}$'),
  -- null until YouTube confirms the owner
  channel_id text references public.channels,
  title text,
  started_at timestamptz,
  -- new: not checked on YouTube yet; pending: waiting to be commented;
  -- posting: claimed by a monitor run; the rest are final.
  state text not null default 'new' check (state in (
    'new', 'pending', 'posting', 'posted', 'member_only', 'unavailable',
    'not_commentable', 'no_timestamps', 'blacklisted', 'expired'
  )),
  comment_id text,
  processed_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.timestamps (
  id bigint generated always as identity primary key,
  video_id text not null references public.streams on delete cascade,
  user_name text not null check (length(user_name) <= 100),
  message text not null default '' check (length(message) <= 200),
  delay smallint not null check (delay between 0 and 300),
  created_at timestamptz not null default now()
);

create index if not exists timestamps_video_id_created_at_idx
  on public.timestamps (video_id, created_at);
create index if not exists streams_queue_idx
  on public.streams (created_at) where state in ('new', 'pending');

-- Only the server's secret key (service_role, which bypasses RLS) gets in.
alter table public.channels enable row level security;
alter table public.streams enable row level security;
alter table public.timestamps enable row level security;

-- One round trip per !ts: link the chat to its stream, save the timestamp,
-- and return what the reply and the Discord post need.
create or replace function public.record_timestamp(
  p_chat_id text,
  p_channel_id text,
  p_user text,
  p_message text,
  p_delay int
)
returns json
language plpgsql
set search_path = ''
as $$
declare
  vid text := public.video_id_from_chat(p_chat_id);
  ts timestamptz;
begin
  if vid is null then
    raise exception 'chat id % carries no video id', left(p_chat_id, 60)
      using errcode = '22023';
  end if;

  insert into public.streams (video_id) values (vid) on conflict do nothing;
  insert into public.timestamps (video_id, user_name, message, delay)
    values (vid, p_user, coalesce(p_message, ''), p_delay)
    returning created_at into ts;

  return (
    select json_build_object(
      'video_id', s.video_id,
      'created_at', ts,
      'title', s.title,
      'started_at', s.started_at,
      'owner_id', s.channel_id,
      'template', c.comment_template,
      'dc_channel_id', c.dc_channel_id
    )
    from public.streams s
    left join public.channels c on c.channel_id = p_channel_id
    where s.video_id = vid
  );
end
$$;

-- Store what YouTube says about a stream and return its state. The first
-- time, that moves it out of 'new': to 'blacklisted' or 'pending'.
create or replace function public.save_stream(
  p_video_id text,
  p_channel_id text,
  p_channel_title text,
  p_title text,
  p_started_at timestamptz
)
returns text
language plpgsql
set search_path = ''
as $$
declare
  st text;
begin
  insert into public.channels (channel_id, title)
    values (p_channel_id, p_channel_title)
    on conflict (channel_id) do update set title = excluded.title;

  update public.streams s
     set channel_id = p_channel_id,
         title = p_title,
         started_at = coalesce(p_started_at, s.started_at),
         state = case
           when s.state <> 'new' then s.state
           when c.blacklisted then 'blacklisted'
           else 'pending'
         end
    from public.channels c
   where c.channel_id = p_channel_id and s.video_id = p_video_id
  returning s.state into st;
  return st;
end
$$;

-- Copy the legacy tables in. Safe to run again: right after deploying, run
-- `select public.backfill_from_legacy();` to pick up what v1 wrote meanwhile.
create or replace function public.backfill_from_legacy()
returns text
language plpgsql
set search_path = ''
as $$
declare
  n_streams int;
  n_timestamps int;
  n_skipped int;
begin
    insert into public.channels (channel_id, title, dc_channel_id, comment_template)
  select distinct on (channel_id)
         channel_id, channel_name, dc_channel_id, channel_template
    from public.yt_channel_db
   where channel_id ~ '^UC[A-Za-z0-9_-]{22}$'
  on conflict (channel_id) do update
     set dc_channel_id = excluded.dc_channel_id,
         comment_template = excluded.comment_template,
         title = coalesce(public.channels.title, excluded.title);

  insert into public.channels (channel_id, blacklisted)
  select distinct channel_id, true
    from public.blacklist_yt_channel
   where channel_id ~ '^UC[A-Za-z0-9_-]{22}$'
  on conflict (channel_id) do update set blacklisted = true;

  insert into public.channels (channel_id, title)
  select distinct on (channel_id) channel_id, channel
    from public.yt_db
   where channel_id ~ '^UC[A-Za-z0-9_-]{22}$'
  on conflict (channel_id) do nothing;

  -- Only rows whose chat really belongs to the video; the rest are the old
  -- wrong links. A stream v1 commented on since the last run is updated
  -- too, so v2 doesn't comment on it again.
  -- Some early rows saved the channel as 'temporary_channel_id': keep the
  -- stream and its state, with the owner unknown.
  insert into public.streams (video_id, channel_id, title, started_at, state)
  select distinct on (y.video_id)
         y.video_id,
         case when y.channel_id ~ '^UC[A-Za-z0-9_-]{22}$' then y.channel_id end,
         y.title,
         nullif(y.stream_start_time::text, '')::timestamp at time zone 'UTC',
         case
           when not coalesce(y.marked, false) then 'pending'
           when y.status in ('member_only', 'unavailable', 'not_commentable',
                             'no_timestamps') then y.status
           else 'posted'
         end
    from public.yt_db y
   where y.video_id = public.video_id_from_chat(y.chat_id)
   order by y.video_id, y.marked desc
  on conflict (video_id) do update
     set state = excluded.state
   where public.streams.state in ('new', 'pending')
     and excluded.state <> 'pending';
  get diagnostics n_streams = row_count;

  -- Chats v1 never linked to a stream (blacklisted, or the link failed).
  -- YouTube will tell the monitor who owns them.
  insert into public.streams (video_id, state)
  select public.video_id_from_chat(chat_id), 'new'
    from public.ts_db
   where public.video_id_from_chat(chat_id) is not null
  on conflict (video_id) do nothing;

  insert into public.timestamps (video_id, user_name, message, delay, created_at)
  select v.vid,
         left(coalesce(t.user_name, ''), 100),
         left(coalesce(t.message, ''), 200),
         least(greatest(coalesce(t.delay, 0), 0), 300),
         coalesce(t.user_timestamp, t.created_at, now())
    from public.ts_db t
   cross join lateral (select public.video_id_from_chat(t.chat_id) as vid) v
   where v.vid is not null
     and not exists (
       select 1 from public.timestamps x
        where x.video_id = v.vid
          and x.created_at = coalesce(t.user_timestamp, t.created_at, now())
          and x.user_name = left(coalesce(t.user_name, ''), 100)
     );
  get diagnostics n_timestamps = row_count;

  select count(*) into n_skipped
    from public.ts_db where public.video_id_from_chat(chat_id) is null;

  -- Nobody wants a comment on a stream from weeks ago: anything still
  -- queued whose newest timestamp is over 7 days old leaves the queue.
  update public.streams s
     set state = 'expired', processed_at = now()
   where s.state in ('new', 'pending')
     and not exists (
       select 1 from public.timestamps t
        where t.video_id = s.video_id
          and t.created_at > now() - interval '7 days'
     );

  raise notice 'backfill: % streams, % timestamps, % timestamps skipped (chat id carries no video id)',
    n_streams, n_timestamps, n_skipped;
  return format('%s streams, %s timestamps, %s skipped', n_streams, n_timestamps, n_skipped);
end
$$;

select public.backfill_from_legacy();

-- Functions are executable by everyone by default; keep them server-only.
revoke execute on function public.record_timestamp(text, text, text, text, int) from public;
revoke execute on function public.save_stream(text, text, text, text, timestamptz) from public;
revoke execute on function public.backfill_from_legacy() from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    revoke execute on function public.record_timestamp(text, text, text, text, int) from anon, authenticated;
    revoke execute on function public.save_stream(text, text, text, text, timestamptz) from anon, authenticated;
    revoke execute on function public.backfill_from_legacy() from anon, authenticated;
    grant execute on function public.record_timestamp(text, text, text, text, int) to service_role;
    grant execute on function public.save_stream(text, text, text, text, timestamptz) to service_role;
  end if;
end
$$;
