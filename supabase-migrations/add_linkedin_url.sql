-- Add linkedin_url column to people table
ALTER TABLE people ADD COLUMN IF NOT EXISTS linkedin_url TEXT;

-- Add company_linkedin_url column to people table
ALTER TABLE people ADD COLUMN IF NOT EXISTS company_linkedin_url TEXT;

-- Create indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_people_linkedin_url ON people(linkedin_url);
CREATE INDEX IF NOT EXISTS idx_people_company_linkedin_url ON people(company_linkedin_url);
