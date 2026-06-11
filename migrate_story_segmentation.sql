-- Migration: add story segmentation columns
-- Run once against your existing database:
--   psql -U <user> -d <dbname> -f migrate_story_segmentation.sql

ALTER TABLE stories ADD COLUMN IF NOT EXISTS story_group_id VARCHAR;
ALTER TABLE stories ADD COLUMN IF NOT EXISTS segment_index INTEGER DEFAULT 0;
ALTER TABLE stories ADD COLUMN IF NOT EXISTS total_segments INTEGER DEFAULT 1;

CREATE INDEX IF NOT EXISTS ix_stories_story_group_id ON stories(story_group_id);
