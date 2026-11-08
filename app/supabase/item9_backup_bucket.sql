-- Simko SI item 9: encrypted cloud backup bucket + per-user RLS policies.
-- Target project: wxvjajecvklfjxppawdx ONLY (never nexkymqahpkvzzlvivfi).
-- Objects are client-side AES-256-GCM ciphertext; Supabase never sees keys.
-- Layout: simko-backups/<auth.uid()>/<backup_id>/{chunk-00000.bin,...,manifest.json}
-- Objects are immutable from the client: no UPDATE policy (no upsert/overwrite).
-- Idempotent: safe to re-run.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('simko-backups', 'simko-backups', false, 8388608, array['application/octet-stream'])
on conflict (id) do update
  set public = false,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "simko_backups_select_own" on storage.objects;
drop policy if exists "simko_backups_insert_own" on storage.objects;
drop policy if exists "simko_backups_delete_own" on storage.objects;

create policy "simko_backups_select_own" on storage.objects
  for select to authenticated
  using (bucket_id = 'simko-backups'
         and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy "simko_backups_insert_own" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'simko-backups'
              and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy "simko_backups_delete_own" on storage.objects
  for delete to authenticated
  using (bucket_id = 'simko-backups'
         and (storage.foldername(name))[1] = (select auth.uid())::text);
