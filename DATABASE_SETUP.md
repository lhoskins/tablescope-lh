# Database Setup & Wiring - RemindMe

## ✅ Completed Tasks

### 1. UI Updates
Added missing sections to the Background collapsible area:
- **Skills** (Amber badges) - Person's professional skills
- **Technologies** (Cyan badges) - Tech stack/tools they use
- **Interests** (Pink badges) - Personal interests

### 2. Database Schema Verification
All required tables exist in Supabase:
- ✅ `people` - Person information
- ✅ `people_business_profiles` - LinkedIn business data
- ✅ `memories` - Conversation notes
- ✅ `memory_people` - Junction table (many-to-many)
- ✅ `events` - Events/conferences
- ✅ `follow_ups` - Action items

### 3. Migration Files
Existing migrations in `supabase-migrations/`:
- `add_keywords_fields.sql` - Adds keywords, companies, industries to memories
- `add_linkedin_url.sql` - Adds LinkedIn URLs to people
- `add_profile_fields.sql` - Adds follower_count, about, experience, education

### 4. API Endpoint Updates
Updated `/app/api/save-memory/route.ts`:
- ✅ Added missing fields: `location`, `opportunities`, `relationship_notes`
- ✅ Added comprehensive error logging with emojis
- ✅ Added detailed success response
- ✅ Proper handling of all array fields (skills, technologies, interests, keywords, companies, industries)

---

## 📊 Complete Data Flow

### Frontend → API → Database

```typescript
// User captures notes and organizes with AI
{
  people: [{
    name, company, role, location,           // → people table
    linkedin_url, company_linkedin_url,      // → people table
    business_needs, opportunities,           // → people table
    skills: [],                              // → people.skills (text[])
    technologies: [],                        // → people.technologies (text[])
    interests: [],                           // → people.interests (text[])
    inspiration_level,                       // → people.inspiration_level
    relationship_potential,                  // → people.relationship_potential
    relationship_notes,                      // → people.relationship_notes
    
    // LinkedIn business data
    follower_count,                          // → people_business_profiles
    about,                                   // → people_business_profiles
    experience: [{...}],                     // → people_business_profiles.experience (jsonb)
    education: [{...}]                       // → people_business_profiles.education (jsonb)
  }],
  
  // Memory metadata
  keywords: [],                              // → memories.keywords (text[])
  companies: [],                             // → memories.companies (text[])
  industries: [],                            // → memories.industries (text[])
  summary: "",                               // → memories.what, energy_summary
  sections: [],                              // → memories.sections (text[])
  
  // Follow-ups
  follow_ups: [{description, priority}],     // → follow_ups table
  
  // Event (optional)
  event: {name, date, location}              // → events table
}
```

---

## 🗄️ Database Tables Detail

### **people**
```sql
- id: uuid (PK)
- user_id: uuid (FK → auth.users)
- name: text
- company: text
- role: text
- location: text
- linkedin_url: text
- company_linkedin_url: text
- business_needs: text
- opportunities: text
- technologies: text[]
- interests: text[]
- skills: text[]
- inspiration_level: text ('low', 'medium', 'high')
- relationship_potential: text ('no', 'maybe', 'yes')
- relationship_notes: text
- created_at: timestamptz
- updated_at: timestamptz
```

### **people_business_profiles**
```sql
- id: uuid (PK)
- person_id: uuid (FK → people)
- user_id: uuid (FK → auth.users)
- linkedin_url: text
- company_linkedin_url: text
- follower_count: int4
- about: text
- experience: jsonb
- education: jsonb
- current_company: text
- role_title: text
- created_at: timestamptz
- updated_at: timestamptz
```

### **memories**
```sql
- id: uuid (PK)
- user_id: uuid (FK → auth.users)
- raw_text: text
- source_type: text
- ai_type: text
- event_id: uuid (FK → events)
- who: text
- what: text
- where_context: text
- when_context: text
- energy_summary: text
- inspiration_score: text
- sections: text[]
- keywords: text[]      ← AI extracted
- companies: text[]     ← AI extracted
- industries: text[]    ← AI extracted
- created_at: timestamptz
- updated_at: timestamptz
```

### **memory_people** (Junction Table)
```sql
- id: uuid (PK)
- memory_id: uuid (FK → memories)
- person_id: uuid (FK → people)
- created_at: timestamptz
```

### **follow_ups**
```sql
- id: uuid (PK)
- user_id: uuid (FK → auth.users)
- person_id: uuid (FK → people)
- memory_id: uuid (FK → memories)
- description: text
- due_date: date
- priority: text ('low', 'medium', 'high')
- status: text ('pending', 'completed')
- created_at: timestamptz
- updated_at: timestamptz
```

### **events**
```sql
- id: uuid (PK)
- user_id: uuid (FK → auth.users)
- name: text
- date: date
- location: text
- description: text
- created_at: timestamptz
- updated_at: timestamptz
```

---

## 🧪 Testing the Database

### 1. Test Database Connection
```bash
# Install tsx if needed
npm install -D tsx

# Run the test script
npx tsx scripts/test-db-connection.ts
```

This will verify:
- ✅ Environment variables are set
- ✅ All tables are accessible
- ✅ No permission errors

### 2. Test the Full Flow (Manual)
1. Start the dev server: `npm run dev`
2. Open http://localhost:3000
3. Add some notes in the capture area
4. Click "Organize with AI"
5. Review the organized data
6. Edit Skills, Technologies, Interests if needed
7. Click "Add Memory" to save
8. Check browser console for logs:
   - ✅ Memory created: [id]
   - ✅ Person created: [id] - [name]
   - ✅ Linked memory to X people
   - ✅ Created X follow-ups

### 3. Verify in Supabase Dashboard
1. Go to your Supabase project
2. Navigate to Table Editor
3. Check these tables for new data:
   - `people` - Should have new person
   - `memories` - Should have new memory with keywords, companies, industries
   - `memory_people` - Should have link between memory and person
   - `follow_ups` - Should have action items (if any)
   - `people_business_profiles` - Should have LinkedIn data (if pasted)

---

## 🔧 Environment Variables Required

Create/update `.env.local`:
```bash
# Supabase
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key  # Optional, for admin operations

# OpenAI
OPENAI_API_KEY=sk-...

# Pinecone (Optional - for vector search)
PINECONE_API_KEY=your-pinecone-key
PINECONE_INDEX_NAME=remind-me
```

---

## 🚀 Next Steps

### Immediate
1. ✅ Run database connection test
2. ✅ Test the full capture → organize → save flow
3. ✅ Verify data appears in Supabase

### Future Enhancements
1. **Authentication** - Add Supabase Auth to protect routes
2. **Data Retrieval** - Build pages to view saved people and memories
3. **Search** - Implement search/filter functionality
4. **Follow-up Management** - Mark as complete, set due dates
5. **Pinecone Integration** - Enable semantic search across memories
6. **Duplicate Detection** - Check if person already exists before inserting

---

## 📝 API Response Format

### Success Response
```json
{
  "success": true,
  "memoryId": "uuid",
  "peopleCount": 1,
  "followUpsCount": 2,
  "eventId": "uuid or null",
  "message": "Memory saved successfully!"
}
```

### Error Response
```json
{
  "error": "Error message details"
}
```

---

## 🐛 Troubleshooting

### "Table does not exist" error
- Run the migration files in Supabase SQL Editor
- Check that RLS (Row Level Security) policies allow inserts

### "Permission denied" error
- Verify `SUPABASE_SERVICE_ROLE_KEY` is set (not just anon key)
- Check RLS policies on tables

### "Missing fields" error
- Verify all migration files have been run
- Check table schema in Supabase dashboard

### Data not saving
- Check browser console for errors
- Check server logs for detailed error messages
- Verify environment variables are loaded

---

## 📚 Key Files

- `app/page.tsx` - Main UI with capture and edit interface
- `app/api/organize/route.ts` - AI organization endpoint
- `app/api/save-memory/route.ts` - Database save endpoint ✅ UPDATED
- `lib/supabase.ts` - Supabase client
- `supabase-migrations/*.sql` - Database schema migrations
- `scripts/test-db-connection.ts` - Database connection test ✅ NEW

---

**Status: ✅ Ready for Testing**

All code is updated and ready. Run the test script and try saving a memory!
