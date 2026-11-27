-- Job Finder tables. Run once in the Supabase SQL Editor, after replacing __DASH_KEY_SHA256__
-- with the SHA-256 (hex) of DASH_KEY. The dashboard sends DASH_KEY in the x-dash-key header;
-- without it, the publishable key can read and change nothing.

create or replace function public.dash_ok() returns boolean language sql stable set search_path = '' as $$
  select encode(sha256(convert_to(coalesce(nullif(current_setting('request.headers', true), '')::json ->> 'x-dash-key', ''), 'utf8')), 'hex')
         = '__DASH_KEY_SHA256__'
$$;

-- data: written by the search (supabase_sync.py). board: your edits on the dashboard, never overwritten by it.
create table if not exists public.applications (
  key text primary key, track text not null default 'design', found_at timestamptz,
  data jsonb not null, board jsonb not null default '{}'::jsonb, hash text not null);
create table if not exists public.jobs (
  id text primary key, track text not null default 'design', seen_at timestamptz, data jsonb not null, hash text not null);
create table if not exists public.docs    (name text primary key, data jsonb not null, hash text not null);
create table if not exists public.resumes (name text primary key, pdf_base64 text not null, hash text not null);
create index if not exists jobs_seen_at on public.jobs (seen_at desc);

do $$ declare t text; begin
  foreach t in array array['applications', 'jobs', 'docs', 'resumes'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant select on public.%I to anon', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('drop policy if exists dash_read on public.%I', t);
    execute format('create policy dash_read on public.%I for select to anon using ((select public.dash_ok()))', t);
  end loop;
end $$;

grant update (board) on public.applications to anon;
drop policy if exists dash_edit on public.applications;
create policy dash_edit on public.applications for update to anon using ((select public.dash_ok())) with check ((select public.dash_ok()));
