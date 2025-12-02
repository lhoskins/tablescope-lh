# RemindMe - My Rolodex Architecture

## Overview
RemindMe is a relationship management application that helps users capture, organize, and manage professional connections using AI-powered organization and LinkedIn profile integration.

## Tech Stack
- **Frontend**: Next.js 13 (App Router), React, TypeScript, Tailwind CSS
- **UI Components**: shadcn/ui (Card, Button, Badge, Textarea, Tabs)
- **Backend**: Next.js API Routes
- **Database**: Supabase (PostgreSQL)
- **AI**: OpenAI GPT-4 (via API)
- **Authentication**: Supabase Auth

## Database Schema

### Tables

#### `people`
Stores information about individuals in the user's network.

```sql
- id: uuid (primary key)
- user_id: uuid (foreign key to auth.users)
- name: text
- company: text
- role: text
- location: text (city, state, country)
- follower_count: integer
- about: text (LinkedIn "About" section)
- mutual_connections: text[] (array of connection names)
- linkedin_url: text (personal profile URL)
- company_linkedin_url: text (company page URL)
- skills: text[] (array of professional skills)
- business_needs: text
- technologies: text[]
- interests: text[]
- inspiration_level: text ('low', 'medium', 'high')
- relationship_potential: text ('no', 'maybe', 'yes')
- created_at: timestamp
- updated_at: timestamp
```

#### `memories`
Stores conversation notes and interactions with people.

```sql
- id: uuid (primary key)
- user_id: uuid (foreign key to auth.users)
- person_id: uuid (foreign key to people)
- raw_notes: text (original user input)
- summary: text (AI-generated summary)
- keywords: text[] (extracted keywords)
- companies: text[] (companies mentioned in conversation)
- industries: text[] (industries mentioned)
- additional_notes: text[] (user-added notes after AI organization)
- context_type: text ('conversation', 'event', 'project', etc.)
- event_name: text
- event_date: date
- created_at: timestamp
- updated_at: timestamp
```

#### `follow_ups`
Stores action items and follow-up tasks.

```sql
- id: uuid (primary key)
- user_id: uuid (foreign key to auth.users)
- person_id: uuid (foreign key to people)
- memory_id: uuid (foreign key to memories)
- description: text
- priority: text ('low', 'medium', 'high')
- status: text ('pending', 'completed')
- due_date: date
- created_at: timestamp
- completed_at: timestamp
```

#### `experiences`
Stores work history for people (from LinkedIn).

```sql
- id: uuid (primary key)
- person_id: uuid (foreign key to people)
- company: text
- role: text
- dates: text (e.g., "2020-2023")
- description: text
- order: integer (for sorting)
```

#### `education`
Stores educational background (from LinkedIn).

```sql
- id: uuid (primary key)
- person_id: uuid (foreign key to people)
- school: text
- degree: text
- field: text
- dates: text
- order: integer (for sorting)
```

## Application Flow

### 1. Capture Phase
**Location**: `app/page.tsx` (lines 750-782)

Users can input information through:
- **Voice Recording**: Speech-to-text using Web Speech API
- **Text Input**: Direct typing in textarea
- **LinkedIn Profile Paste**: Paste entire LinkedIn profile for parsing
- **Context Selection**: Choose type (conversation, event, panel, project, trip)

**Key State Variables**:
- `captureText`: Raw user input
- `contextType`: Type of interaction
- `linkedInProfilePaste`: Pasted LinkedIn data
- `isRecording`: Voice recording status

### 2. AI Organization Phase
**Location**: `app/api/organize/route.ts`

**Process**:
1. User clicks "Organize with AI"
2. Frontend sends raw notes + LinkedIn data to `/api/organize`
3. OpenAI GPT-4 extracts structured data:
   - People (name, company, role, location, follower_count, about, mutual_connections, skills, experience, education)
   - Keywords (conversation topics)
   - Companies (mentioned in conversation only)
   - Industries (from LinkedIn or conversation)
   - Follow-ups (action items with priority)
   - Summary (bullet points of conversation)

**AI Prompt Structure** (lines 37-96):
```
Extract from conversation notes and LinkedIn profile:
1. People: name, location, company, role, follower_count, about, mutual_connections, 
   linkedin_url, company_linkedin_url, experience[], education[], skills[], 
   business_needs, technologies[], interests[], inspiration_level, relationship_potential
2. Keywords: conversation topics
3. Companies: ONLY from conversation (not LinkedIn work history)
4. Industries: from LinkedIn or conversation
5. Follow-ups: action items with priority
6. Summary: bullet point summary
```

**Response Format**: JSON
```json
{
  "people": [...],
  "keywords": [...],
  "companies": [...],
  "industries": [...],
  "follow_ups": [...],
  "summary": "..."
}
```

### 3. Edit/Preview Phase
**Location**: `app/page.tsx` (lines 792-1020)

After AI organization, user enters **edit mode** (default state):

**UI Sections** (in order):
1. **Person Info Card** (lines 796-810)
   - Name (bold, large)
   - Location (with 📍 icon)
   - Company
   - Role
   - Followers count

2. **About me** (lines 812-828) - Collapsible, collapsed by default
   - LinkedIn "About" section

3. **Background** (lines 830-943) - Collapsible, collapsed by default
   - Keywords (editable badges)
   - Companies (editable badges)
   - Industries (editable badges)

4. **My Notes** (lines 945-975)
   - Original conversation text
   - Additional notes (user can add more)

5. **Follow-ups** (lines 977-1007)
   - Action items (user can add/remove)

**Editing Features**:
- **Add items**: Type in input field, press Enter
- **Remove items**: Click × on badge or item
- **All sections always visible**: Show placeholder if empty

**State Management**:
- `isEditingPreview`: Always true after AI organize
- `editedPreview`: Mutable copy of AI response
- `showLinkedInData`: Background section collapsed state
- `showAboutMe`: About me section collapsed state

### 4. Save Phase
**Location**: `app/api/save-memory/route.ts`

**Process**:
1. User clicks "Add Memory"
2. Frontend sends `editedPreview` to `/api/save-memory`
3. Backend saves to Supabase:
   - Insert/update `people` record
   - Insert `memories` record
   - Insert `follow_ups` records
   - Insert `experiences` records
   - Insert `education` records

**Database Operations**:
```typescript
// 1. Upsert person
const { data: person } = await supabase
  .from('people')
  .upsert({
    name, company, role, location, follower_count, about,
    mutual_connections, linkedin_url, company_linkedin_url,
    skills, business_needs, technologies, interests,
    inspiration_level, relationship_potential
  })
  .select()

// 2. Insert memory
const { data: memory } = await supabase
  .from('memories')
  .insert({
    person_id: person.id,
    raw_notes: captureText,
    summary, keywords, companies, industries,
    additional_notes, context_type, event_name, event_date
  })

// 3. Insert follow-ups
for (const followUp of follow_ups) {
  await supabase.from('follow_ups').insert({
    person_id: person.id,
    memory_id: memory.id,
    description: followUp.description,
    priority: followUp.priority
  })
}

// 4. Insert experiences
for (const exp of experiences) {
  await supabase.from('experiences').insert({
    person_id: person.id,
    company: exp.company,
    role: exp.role,
    dates: exp.dates,
    description: exp.description
  })
}

// 5. Insert education
for (const edu of education) {
  await supabase.from('education').insert({
    person_id: person.id,
    school: edu.school,
    degree: edu.degree,
    field: edu.field,
    dates: edu.dates
  })
}
```

## Key Files

### Frontend
- `app/page.tsx` (1313 lines)
  - Main UI component
  - Capture interface
  - Edit/preview interface
  - State management

### API Routes
- `app/api/organize/route.ts`
  - AI organization endpoint
  - OpenAI integration
  - Data extraction logic

- `app/api/save-memory/route.ts`
  - Database save endpoint
  - Supabase operations
  - Data persistence

### Database
- `lib/supabase.ts`
  - Supabase client configuration
  - Database connection

- `supabase-migrations/`
  - `add_location_mutual_connections.sql`: Adds location, mutual_connections, skills columns
  - `add_linkedin_url.sql`: Adds linkedin_url, company_linkedin_url columns

## Current Status

### ✅ Completed
1. UI for capture (voice, text, LinkedIn paste)
2. AI organization with OpenAI
3. Edit mode with all sections
4. Editable badges (keywords, companies, industries)
5. Editable follow-ups
6. Editable additional notes
7. Collapsible sections (About me, Background)
8. Person info display

### ⚠️ Needs Implementation
1. **Database wiring** - `save-memory` API needs to be implemented
2. **Authentication** - User login/signup
3. **Data retrieval** - View saved memories and people
4. **Search/filter** - Find people and memories
5. **Follow-up management** - Mark as complete, set due dates

## Environment Variables

Required in `.env.local`:
```
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
OPENAI_API_KEY=your_openai_api_key
```

## Data Flow Diagram

```
User Input (Voice/Text/LinkedIn)
    ↓
Capture Text State
    ↓
Click "Organize with AI"
    ↓
POST /api/organize
    ↓
OpenAI GPT-4 Extraction
    ↓
Structured JSON Response
    ↓
Edit Mode (editedPreview state)
    ↓
User Edits (add/remove items)
    ↓
Click "Add Memory"
    ↓
POST /api/save-memory
    ↓
Supabase Database
    ↓
Success/Error Response
```

## Next Steps for Database Implementation

1. **Create Supabase tables** using migrations
2. **Implement `/api/save-memory` endpoint**
3. **Test data persistence**
4. **Add error handling**
5. **Implement data retrieval** (view saved people/memories)
6. **Add authentication** (protect routes)
