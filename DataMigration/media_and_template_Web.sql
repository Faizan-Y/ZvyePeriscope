-- Zyvefit Nutritionist Console — additive migration (review before running)
-- Run this ONLY against your TEST database first, after taking a backup.
-- This file is intentionally NOT applied by the FastAPI app.
-- Assumes the existing public.tiers, public.members, and public.templates tables
-- use the column names in the Zyvefit schema shared for this project.

BEGIN;

-- Portal authentication only; contains password hashes, never plaintext passwords.
-- Run init_auth.py separately to provision the initial administrator interactively.
-- This migration targets public; init_auth.py uses DATABASE_SCHEMA if configured.
CREATE TABLE IF NOT EXISTS public.auth_users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.media_assets (
    media_asset_id BIGSERIAL PRIMARY KEY,
    display_name VARCHAR(140) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    mime_type VARCHAR(150) NOT NULL,
    message_type VARCHAR(30) NOT NULL,
    storage_path TEXT NOT NULL UNIQUE,
    media_url TEXT NOT NULL UNIQUE,
    file_size_bytes BIGINT NULL CHECK (file_size_bytes IS NULL OR file_size_bytes > 0),
    audience_scope VARCHAR(20) NOT NULL DEFAULT 'SHARED',
    tier_id INTEGER NULL REFERENCES public.tiers(tier_id) ON DELETE RESTRICT,
    member_id INTEGER NULL REFERENCES public.members(member_id) ON DELETE RESTRICT,
    internal_note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT media_assets_message_type_check
      CHECK (message_type IN ('IMAGE','VIDEO','AUDIO','DOCUMENT')),
    CONSTRAINT media_assets_scope_check CHECK (
      (audience_scope = 'SHARED' AND tier_id IS NULL AND member_id IS NULL) OR
      (audience_scope = 'TIER' AND tier_id IS NOT NULL AND member_id IS NULL) OR
      (audience_scope = 'MEMBER' AND tier_id IS NULL AND member_id IS NOT NULL)
    )
);

ALTER TABLE public.templates
    ADD COLUMN IF NOT EXISTS audience_scope VARCHAR(20) NOT NULL DEFAULT 'SHARED';
ALTER TABLE public.templates
    ADD COLUMN IF NOT EXISTS tier_id INTEGER NULL REFERENCES public.tiers(tier_id) ON DELETE RESTRICT;
ALTER TABLE public.templates
    ADD COLUMN IF NOT EXISTS member_id INTEGER NULL REFERENCES public.members(member_id) ON DELETE RESTRICT;
ALTER TABLE public.templates
    ADD COLUMN IF NOT EXISTS media_asset_id BIGINT NULL REFERENCES public.media_assets(media_asset_id) ON DELETE RESTRICT;
ALTER TABLE public.templates
    ADD COLUMN IF NOT EXISTS is_media_template BOOLEAN NOT NULL DEFAULT FALSE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'templates_audience_scope_check'
      AND conrelid = 'public.templates'::regclass
  ) THEN
    ALTER TABLE public.templates ADD CONSTRAINT templates_audience_scope_check CHECK (
      (audience_scope = 'SHARED' AND tier_id IS NULL AND member_id IS NULL) OR
      (audience_scope = 'TIER' AND tier_id IS NOT NULL AND member_id IS NULL) OR
      (audience_scope = 'MEMBER' AND tier_id IS NULL AND member_id IS NOT NULL)
    );
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_media_assets_scope_tier
    ON public.media_assets (audience_scope, tier_id);
CREATE INDEX IF NOT EXISTS idx_media_assets_member
    ON public.media_assets (member_id);
CREATE INDEX IF NOT EXISTS idx_templates_media_asset_id
    ON public.templates (media_asset_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_templates_one_media_template
    ON public.templates (media_asset_id)
    WHERE is_media_template = TRUE AND media_asset_id IS NOT NULL;

-- Latest dashboard scheduling and request-id changes (ONLINE_ONCE).
-- Reuses the existing message_schedules and message_logs tables; apply only after
-- the base schema and its scheduler deduplication index are in place. The five-minute
-- schedule removal rule is enforced by the API and requires no additional SQL.
-- Existing recurrence types retain their rules; review constraints against the
-- actual target schema and back up before applying this migration.
ALTER TABLE public.message_schedules ADD COLUMN IF NOT EXISTS online_date DATE;
ALTER TABLE public.message_schedules ADD COLUMN IF NOT EXISTS online_promotion BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.message_schedules ADD COLUMN IF NOT EXISTS online_request_id UUID;
ALTER TABLE public.message_schedules ADD COLUMN IF NOT EXISTS online_request_fingerprint TEXT;
ALTER TABLE public.message_schedules ADD COLUMN IF NOT EXISTS online_completed_at TIMESTAMPTZ;
ALTER TABLE public.message_schedules ADD COLUMN IF NOT EXISTS online_started_at TIMESTAMPTZ;
ALTER TABLE public.message_schedules ADD COLUMN IF NOT EXISTS online_status TEXT;
ALTER TABLE public.message_schedules ALTER COLUMN phase_id DROP NOT NULL;
ALTER TABLE public.message_schedules DROP CONSTRAINT IF EXISTS chk_schedule_type;
ALTER TABLE public.message_schedules ADD CONSTRAINT chk_schedule_type
    CHECK (schedule_type IN ('ONCE', 'DAILY', 'WEEKLY', 'FORTNIGHTLY', 'HOURLY', 'ONLINE_ONCE'));
-- On the first run PostgreSQL may report that this constraint does not exist;
-- this NOTICE is expected. The next statement creates it before COMMIT.
ALTER TABLE public.message_schedules DROP CONSTRAINT IF EXISTS chk_online_schedule_fields;
ALTER TABLE public.message_schedules ADD CONSTRAINT chk_online_schedule_fields CHECK (
    (schedule_type = 'ONLINE_ONCE' AND online_date IS NOT NULL AND send_time IS NOT NULL AND online_request_id IS NOT NULL)
    OR (schedule_type <> 'ONLINE_ONCE' AND phase_id IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_online_schedule_request ON public.message_schedules (online_request_id) WHERE online_request_id IS NOT NULL;

COMMIT;
