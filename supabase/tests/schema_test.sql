-- Run with: supabase test db
begin;
create extension if not exists pgtap with schema extensions;
select plan(35);

-- Nightbot chat ids. NYLA carries I9N75SNAi5w of UCQuhx1QTbSZ7yvaOaNAeZzg;
-- B and C carry bbbbbbbbbbb and ccccccccccc of UCaaaaaaaaaaaaaaaaaaaaaa.
\set nyla '''KicKGFVDUXVoeDFRVGJTWjd5dmFPYU5BZVp6ZxILSTlONzVTTkFpNXc'''
\set b '''KicKGFVDYWFhYWFhYWFhYWFhYWFhYWFhYWFhYRILYmJiYmJiYmJiYmI'''
\set c '''KicKGFVDYWFhYWFhYWFhYWFhYWFhYWFhYWFhYRILY2NjY2NjY2NjY2M'''
\set owner '''UCQuhx1QTbSZ7yvaOaNAeZzg'''

-- video_id_from_chat ---------------------------------------------------------
select is(public.video_id_from_chat(:nyla), 'I9N75SNAi5w', 'decodes a Nightbot chat id');
select is(public.video_id_from_chat(repeat('c', 30)), null, 'garbage gives null');
select is(public.video_id_from_chat('not base64 !!'), null, 'non-base64 gives null');
select is(public.video_id_from_chat(null), null, 'null gives null');

-- record_timestamp -----------------------------------------------------------
insert into public.channels (channel_id, comment_template, dc_channel_id)
values (:owner, 'tpl {user}', '123');

select is(
  public.record_timestamp(:nyla, :owner, '@u', 'clutch', 22)->>'video_id',
  'I9N75SNAi5w', 'the stream comes from the chat id');
select is(
  public.record_timestamp(:nyla, :owner, '@v', '', 42)->>'template',
  'tpl {user}', 'the channel''s settings come back');
select is((select count(*)::int from public.streams where video_id = 'I9N75SNAi5w'), 1,
  'two !ts, one stream');
select is((select count(*)::int from public.timestamps where video_id = 'I9N75SNAi5w'), 2,
  'two !ts, two timestamps');
select is((select state from public.streams where video_id = 'I9N75SNAi5w'), 'new',
  'a stream starts unchecked');
select is((select channel_id from public.streams where video_id = 'I9N75SNAi5w'), null,
  'the request does not decide who owns the stream');
select is(public.record_timestamp(:b, 'UC' || repeat('z', 22), 'u', '', 22)->>'template', null,
  'an unknown channel just has no settings');

select throws_ok($$select public.record_timestamp('garbage-garbage-garbage', 'x', 'u', '', 22)$$,
  '22023', null, 'a chat id with no video is refused');
select throws_ok(format('select public.record_timestamp(%L, %L, %L, %L, 301)',
  :nyla, :owner, 'u', ''), '23514', null, 'delay over 300 is refused');
select throws_ok(format('select public.record_timestamp(%L, %L, %L, %L, 22)',
  :nyla, :owner, 'u', repeat('x', 201)), '23514', null, 'a message over 200 is refused');

-- save_stream ----------------------------------------------------------------
select is(public.save_stream('I9N75SNAi5w', :owner, 'Nyla', 'Stream', '2025-10-25T10:00:00Z'),
  'pending', 'a checked stream joins the queue');
select is((select started_at from public.streams where video_id = 'I9N75SNAi5w'),
  '2025-10-25T10:00:00Z'::timestamptz, 'and keeps its start time');
select is(public.save_stream('I9N75SNAi5w', :owner, 'Nyla', 'Stream', null),
  'pending', 'saving again changes nothing');
select is((select started_at from public.streams where video_id = 'I9N75SNAi5w'),
  '2025-10-25T10:00:00Z'::timestamptz, 'a missing start time does not erase the known one');

insert into public.channels (channel_id, blacklisted) values ('UC' || repeat('a', 22), true);
select is(public.save_stream('bbbbbbbbbbb', 'UC' || repeat('a', 22), 'A', 'S', null),
  'blacklisted', 'a blacklisted owner takes the stream out');

-- claiming (what the monitor does before posting) ----------------------------
create function pg_temp.claim() returns int language sql as $$
  with c as (update public.streams set state = 'posting'
              where video_id = 'I9N75SNAi5w' and state = 'pending' returning 1)
  select count(*)::int from c
$$;
select is(pg_temp.claim(), 1, 'the first claim wins');
select is(pg_temp.claim(), 0, 'a second run cannot claim it again');

-- backfill_from_legacy -------------------------------------------------------
insert into public.yt_channel_db (channel_id, channel_name, channel_template)
values ('UC' || repeat('d', 22), 'D', 'custom {user}');
insert into public.yt_db (chat_id, video_id, channel_id, channel, title, marked, status, stream_start_time)
values
  -- the chat really is ccccccccccc's
  (:c, 'ccccccccccc', 'UC' || repeat('d', 22), 'D', 'right', false, 'live', '2025-10-25 09:00:00'),
  -- an old wrong link: chat c pointed at another video
  (:c, 'wwwwwwwwwww', 'UC' || repeat('d', 22), 'D', 'wrong', true, 'ended', null);
insert into public.ts_db (chat_id, channel_id, user_name, message, delay, user_timestamp)
values
  (:c, 'UC' || repeat('d', 22), 'old', 'gg', 22, now() - interval '1 hour'),
  (:c, 'UC' || repeat('d', 22), 'old', repeat('x', 300), 999, now() - interval '30 minutes'),
  ('garbage-garbage-garbage', 'UC' || repeat('d', 22), 'old', '', 22, now());

select lives_ok('select public.backfill_from_legacy()', 'backfill runs');
select lives_ok('select public.backfill_from_legacy()', 'and runs again');
select is((select comment_template from public.channels where channel_id = 'UC' || repeat('d', 22)),
  'custom {user}', 'channel settings move over');
select is((select state from public.streams where video_id = 'ccccccccccc'), 'pending',
  'an uncommented stream stays queued');
select is((select started_at from public.streams where video_id = 'ccccccccccc'),
  '2025-10-25T09:00:00Z'::timestamptz, 'its start time is read as UTC');
select is((select count(*)::int from public.streams where video_id = 'wwwwwwwwwww'), 0,
  'wrong links are left behind');
select is((select count(*)::int from public.timestamps where video_id = 'ccccccccccc'), 2,
  'timestamps move once, however often it runs');
select is((select max(delay)::int from public.timestamps where video_id = 'ccccccccccc'), 300,
  'out-of-range delays are clamped');

update public.yt_db set marked = true, status = 'ended' where video_id = 'ccccccccccc';
select lives_ok('select public.backfill_from_legacy()', 'a later run');
select is((select state from public.streams where video_id = 'ccccccccccc'), 'posted',
  'picks up comments v1 posted meanwhile');

update public.ts_db set user_timestamp = now() - interval '8 days' where chat_id = :c;
update public.timestamps set created_at = now() - interval '8 days' where video_id = 'ccccccccccc';
update public.yt_db set marked = false where video_id = 'ccccccccccc';
update public.streams set state = 'pending' where video_id = 'ccccccccccc';
select lives_ok('select public.backfill_from_legacy()', 'and another');
select is((select state from public.streams where video_id = 'ccccccccccc'), 'expired',
  'week-old streams are not commented any more');

-- access -----------------------------------------------------------------------
set local role anon;
select throws_ok(format('select public.record_timestamp(%L, %L, %L, %L, 22)', :nyla, :owner, 'u', ''),
  '42501', null, 'the public anon key cannot write');
select is((select count(*)::int from public.timestamps), 0, 'nor read');
reset role;

select * from finish();
rollback;
