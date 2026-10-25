-- Zyvefit Nutritionist Console — additive migration (review before running)
-- Run this ONLY against your TEST database first, after taking a backup.
-- This file is intentionally NOT applied by the FastAPI app.
-- Assumes the existing public.tiers, public.members, and public.templates tables
-- use the column names in the Zyvefit schema shared for this project.

BEGIN;

CREATE TABLE IF NOT EXISTS public.media_assets (
    media_asset_id BI GSERIAL PRIMARY KEY,
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

COMMIT;
