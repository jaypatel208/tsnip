-- Contract step of the v2 migration. Applied after 8 days of v2 in production
-- with no writes to these tables, and every valid row confirmed in the new
-- ones. A full dump was kept outside the repo before dropping them.

drop function if exists public.backfill_from_legacy();
drop table if exists public.ts_db;
drop table if exists public.yt_db;
drop table if exists public.yt_channel_db;
drop table if exists public.blacklist_yt_channel;
