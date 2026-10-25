-- Contract step of the v2 migration. Not applied yet on purpose.
--
-- Once v2 has run in production for about two weeks without problems:
--   1. select public.backfill_from_legacy();  -- one last catch-up, if needed
--   2. mv supabase/pending/drop_legacy.sql supabase/migrations/<timestamp>_drop_legacy.sql
--   3. supabase db push

drop function if exists public.backfill_from_legacy();
drop table if exists public.ts_db;
drop table if exists public.yt_db;
drop table if exists public.yt_channel_db;
drop table if exists public.blacklist_yt_channel;
