-- Add keywords, companies, and industries to memories table
ALTER TABLE memories ADD COLUMN IF NOT EXISTS keywords TEXT[];
ALTER TABLE memories ADD COLUMN IF NOT EXISTS companies TEXT[];
ALTER TABLE memories ADD COLUMN IF NOT EXISTS industries TEXT[];

-- Create indexes for better search performance
CREATE INDEX IF NOT EXISTS idx_memories_keywords ON memories USING GIN (keywords);
CREATE INDEX IF NOT EXISTS idx_memories_companies ON memories USING GIN (companies);
CREATE INDEX IF NOT EXISTS idx_memories_industries ON memories USING GIN (industries);
