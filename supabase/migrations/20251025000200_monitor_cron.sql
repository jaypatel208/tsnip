-- Run the stream monitor every 22 minutes from the database itself. GitHub
-- Actions schedules ran about 6 times a day instead of 48.
--
-- The cron secret lives in Vault, never in this repo. Set it once (and again
-- whenever CRON_SECRET changes in Vercel):
--   select vault.create_secret('<CRON_SECRET>', 'cron_secret');
--   select vault.update_secret(id, '<CRON_SECRET>') from vault.secrets where name = 'cron_secret';
--
-- Responses are kept for 6 hours in net._http_response.

create extension if not exists pg_cron;
create extension if not exists pg_net with schema extensions;

-- Rescheduling under the same name replaces the job, so this is re-runnable.
select cron.schedule(
  'monitor-streams',
  '*/22 * * * *',
  $$
  select net.http_get(
    url := 'https://tsnip.vercel.app/api/monitor-streams',
    headers := jsonb_build_object(
      'X-Cron-Secret',
      (select decrypted_secret from vault.decrypted_secrets where name = 'cron_secret')
    ),
    -- Vercel allows the function 300s and the monitor stops at 240s.
    timeout_milliseconds := 290000
  );
  $$
);
