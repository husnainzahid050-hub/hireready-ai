-- HireReady AI: initial schema
-- Security model: the backend talks to Postgres with the service role (bypasses RLS).
-- The browser NEVER talks to the database. So: RLS on every table, no policies,
-- and all grants revoked from anon/authenticated => the public Data API exposes nothing.
--
-- NOTE: vector(768) must match EMBEDDING_DIM in the backend env.

create extension if not exists vector with schema extensions;

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------
create type public.session_status as enum ('created', 'analyzed', 'interviewing', 'completed');
create type public.interview_mode as enum ('voice', 'text');
create type public.difficulty_level as enum ('junior', 'mid');
create type public.interview_kind as enum ('technical', 'behavioral', 'mixed');
create type public.document_kind as enum ('cv', 'jd');
create type public.question_type as enum
  ('technical', 'project', 'gap_probe', 'behavioral', 'role_fit', 'follow_up');

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------
create table public.sessions (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid null,
  guest_token_hash text not null,
  status           public.session_status not null default 'created',
  role_title       text null check (char_length(role_title) <= 200),
  mode             public.interview_mode not null default 'text',
  difficulty       public.difficulty_level not null default 'junior',
  interview_type   public.interview_kind not null default 'mixed',
  email_opt_in     boolean not null default false,
  email            text null check (char_length(email) <= 320),
  is_demo          boolean not null default false,
  created_at       timestamptz not null default now(),
  expires_at       timestamptz not null default (now() + interval '7 days')
);
create index sessions_expires_at_idx on public.sessions (expires_at);

create table public.documents (
  id           uuid primary key default gen_random_uuid(),
  session_id   uuid not null references public.sessions (id) on delete cascade,
  kind         public.document_kind not null,
  raw_text     text not null check (char_length(raw_text) <= 60000),
  structured   jsonb null,
  content_hash text not null,
  created_at   timestamptz not null default now(),
  unique (session_id, kind)
);
create index documents_content_hash_idx on public.documents (content_hash);

create table public.doc_chunks (
  id          uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.documents (id) on delete cascade,
  chunk_index int not null,
  content     text not null,
  embedding   extensions.vector(768) not null,
  tsv         tsvector generated always as (to_tsvector('english', content)) stored,
  metadata    jsonb not null default '{}'::jsonb,
  unique (document_id, chunk_index)
);

create table public.knowledge_chunks (
  id           uuid primary key default gen_random_uuid(),
  source_file  text not null,
  chunk_index  int not null,
  competency   text not null,
  level        text not null default 'all' check (level in ('all', 'junior', 'mid')),
  content      text not null,
  content_hash text not null unique,
  embedding    extensions.vector(768) not null,
  tsv          tsvector generated always as (to_tsvector('english', content)) stored,
  metadata     jsonb not null default '{}'::jsonb,
  updated_at   timestamptz not null default now()
);
create index knowledge_chunks_competency_idx on public.knowledge_chunks (competency, level);
create index knowledge_chunks_source_idx on public.knowledge_chunks (source_file);

create table public.gap_analyses (
  session_id       uuid primary key references public.sessions (id) on delete cascade,
  match_score      int not null check (match_score between 0 and 100),
  breakdown        jsonb not null,
  gaps             jsonb not null,
  strengths        jsonb not null,
  likely_questions jsonb not null,
  prep_plan        jsonb not null,
  created_at       timestamptz not null default now()
);

create table public.questions (
  id                 uuid primary key default gen_random_uuid(),
  session_id         uuid not null references public.sessions (id) on delete cascade,
  order_index        int not null,
  type               public.question_type not null,
  competency         text null,
  text               text not null,
  parent_question_id uuid null references public.questions (id) on delete cascade,
  rubric_chunk_ids   uuid[] not null default '{}',
  created_at         timestamptz not null default now()
);
create index questions_session_idx on public.questions (session_id, order_index);

create table public.answers (
  id                uuid primary key default gen_random_uuid(),
  question_id       uuid not null references public.questions (id) on delete cascade,
  transcript        text not null check (char_length(transcript) <= 10000),
  duration_seconds  real null,
  words_per_minute  real null,
  filler_count      int null,
  filler_breakdown  jsonb null,
  long_pauses       int null,
  scores            jsonb null,
  feedback          jsonb null,
  created_at        timestamptz not null default now()
);
create index answers_question_idx on public.answers (question_id);

create table public.interview_state (
  session_id uuid primary key references public.sessions (id) on delete cascade,
  state      jsonb not null,
  updated_at timestamptz not null default now()
);

create table public.reports (
  session_id  uuid primary key references public.sessions (id) on delete cascade,
  report      jsonb not null,
  share_token text unique null,
  emailed_at  timestamptz null,
  created_at  timestamptz not null default now()
);

create table public.reminders (
  session_id        uuid primary key references public.sessions (id) on delete cascade,
  next_send_date    date not null,
  day_index         int not null default 0 check (day_index between 0 and 7),
  active            boolean not null default true,
  unsubscribe_token text not null unique
);
create index reminders_due_idx on public.reminders (next_send_date) where active;

-- ---------------------------------------------------------------------------
-- Vector + full-text indexes
-- ---------------------------------------------------------------------------
create index doc_chunks_embedding_idx
  on public.doc_chunks using hnsw (embedding extensions.vector_cosine_ops);
create index doc_chunks_tsv_idx on public.doc_chunks using gin (tsv);
create index knowledge_chunks_embedding_idx
  on public.knowledge_chunks using hnsw (embedding extensions.vector_cosine_ops);
create index knowledge_chunks_tsv_idx on public.knowledge_chunks using gin (tsv);

-- ---------------------------------------------------------------------------
-- Row Level Security: ON everywhere, no policies (backend uses service role).
-- ---------------------------------------------------------------------------
alter table public.sessions         enable row level security;
alter table public.documents        enable row level security;
alter table public.doc_chunks       enable row level security;
alter table public.knowledge_chunks enable row level security;
alter table public.gap_analyses     enable row level security;
alter table public.questions        enable row level security;
alter table public.answers          enable row level security;
alter table public.interview_state  enable row level security;
alter table public.reports          enable row level security;
alter table public.reminders        enable row level security;

-- Defence in depth: remove default grants so anon/authenticated can't even try.
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke execute on functions from anon, authenticated, public;
