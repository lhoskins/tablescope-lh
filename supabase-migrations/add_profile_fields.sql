-- Add LinkedIn profile fields to people table
ALTER TABLE people ADD COLUMN IF NOT EXISTS follower_count INTEGER;
ALTER TABLE people ADD COLUMN IF NOT EXISTS about TEXT;
ALTER TABLE people ADD COLUMN IF NOT EXISTS experience JSONB;
ALTER TABLE people ADD COLUMN IF NOT EXISTS education JSONB;

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_people_follower_count ON people(follower_count);
CREATE INDEX IF NOT EXISTS idx_people_experience ON people USING GIN (experience);
CREATE INDEX IF NOT EXISTS idx_people_education ON people USING GIN (education);

-- Example of experience JSONB structure:
-- [
--   {
--     "company": "Integral Ad Science",
--     "role": "Vice President of Enterprise Accounts, East",
--     "dates": "Jun 2025 - Present",
--     "description": "..."
--   }
-- ]

-- Example of education JSONB structure:
-- [
--   {
--     "school": "Ithaca College",
--     "degree": "Bachelor of Science",
--     "field": "Business Administration; Marketing",
--     "dates": "2006 - 2010"
--   }
-- ]
