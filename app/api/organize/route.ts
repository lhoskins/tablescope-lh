import { NextResponse } from "next/server";
import OpenAI from "openai";

const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
});

export async function POST(request: Request) {
  try {
    const { rawText, contextType, persistentEvent, sectionName, panelParticipants, linkedInUrls, companyLinkedInUrls, parsedProfileData, parsedProfilesArray } = await request.json();

    if (!rawText) {
      return NextResponse.json(
        { error: "No text provided" },
        { status: 400 }
      );
    }

    // Build context for AI
    let contextPrompt = "";
    if (contextType) {
      contextPrompt += `\n\nContext type: ${contextType}. Tag this memory appropriately in the sections array.`;
    }
    if (persistentEvent) {
      contextPrompt += `\n\nIMPORTANT: This note is from the event: "${persistentEvent}". Include this event in your response.`;
    }
    if (sectionName) {
      contextPrompt += `\n\nThis note is from the session/section: "${sectionName}". Include this context in the summary.`;
    }
    if (panelParticipants) {
      contextPrompt += `\n\nPanel participants: ${panelParticipants}. These are the people on the panel. Extract information about each person mentioned.`;
    }
    if (linkedInUrls) {
      contextPrompt += `\n\nLinkedIn profile URLs provided:\n${linkedInUrls}\n\nMatch these URLs to the people mentioned in the notes. Extract names from the URLs if possible and associate each URL with the corresponding person.`;
    }
    if (companyLinkedInUrls) {
      contextPrompt += `\n\nCompany LinkedIn URLs provided:\n${companyLinkedInUrls}\n\nExtract company names from these URLs and associate them with the people mentioned. Store these company URLs for later use with company insights scraping.`;
    }

    const completion = await openai.chat.completions.create({
      model: "gpt-4o-mini",
      messages: [
        {
          role: "system",
          content: `You are an AI assistant that helps organize personal notes about people and networking encounters.

Extract and structure the following information from the user's notes:

1. **People**: Array of people mentioned with:
   - name (or null if not mentioned)
   - company
   - role
   - linkedin_url (personal profile URL if provided)
   - company_linkedin_url (company page URL if provided)
   - follower_count (if available from pasted profile)
   - about (summary/bio from LinkedIn)
   - experience (array of work history: {company, role, dates, description})
   - education (array of schools and degrees)
   - business_needs
   - technologies (array)
   - interests (array)
   - skills (array)
   - inspiration_level ("low", "medium", or "high")
   - relationship_potential ("no", "maybe", or "yes")

2. **Event**: If an event is mentioned:
   - name
   - date (if mentioned)
   - location

3. **Summary**: A brief summary of the encounter/notes

4. **Keywords**: Array of important keywords, topics, and themes. Extract from:
   - LinkedIn skills (e.g., "Enterprise Sales", "Marketing Technology", "Sales Mentorship")
   - Conversation topics (e.g., "trains", "locomotives", "quantum physics")
   - Technologies mentioned (e.g., "MarTech", "AdTech", "SaaS")
   - Any other relevant topics

5. **Companies**: Array of ALL companies mentioned. Extract from:
   - Current company (from LinkedIn)
   - All previous companies (from LinkedIn experience history)
   - Companies mentioned in conversation
   
6. **Industries**: Array of industries. Infer from:
   - Person's role and company (e.g., if they work in "Enterprise Sales" at an "AdTech" company, include "advertising", "technology", "sales")
   - LinkedIn experience (e.g., "healthcare", "biotech", "financial services", "retail", "manufacturing")
   - Conversation context

7. **Follow-ups**: Array of suggested follow-up actions with:
   - description
   - priority ("low", "medium", or "high")

8. **Sections**: Array of applicable categories from: ["personal", "business", "projects", "relationships", "todos", "events", "trips"]

Return ONLY valid JSON with no additional text.${contextPrompt}`,
        },
        {
          role: "user",
          content: rawText,
        },
      ],
      response_format: { type: "json_object" },
      temperature: 0.7,
    });

    const result = JSON.parse(completion.choices[0].message.content || "{}");

    // If multiple parsed profiles exist (panel scenario), use them directly
    if (parsedProfilesArray && parsedProfilesArray.length > 0) {
      result.people = parsedProfilesArray;
    }
    // If single parsed LinkedIn data exists, merge it with AI results
    else if (parsedProfileData) {
      // Merge parsed LinkedIn data into the first person or create new person
      if (!result.people || result.people.length === 0) {
        result.people = [parsedProfileData];
      } else {
        // Merge parsed data into first person
        result.people[0] = {
          ...parsedProfileData,
          ...result.people[0],
          // Keep parsed LinkedIn data, but allow AI to add additional fields
          name: parsedProfileData.name || result.people[0].name,
          company: parsedProfileData.company || result.people[0].company,
          role: parsedProfileData.role || result.people[0].role,
          about: parsedProfileData.about || result.people[0].about,
          experience: parsedProfileData.experience || result.people[0].experience,
          education: parsedProfileData.education || result.people[0].education,
          skills: parsedProfileData.skills || result.people[0].skills,
          follower_count: parsedProfileData.follower_count || result.people[0].follower_count,
          linkedin_url: parsedProfileData.linkedin_url || result.people[0].linkedin_url,
          company_linkedin_url: parsedProfileData.company_linkedin_url || result.people[0].company_linkedin_url,
        };
      }
    }

    return NextResponse.json(result);
  } catch (error: any) {
    console.error("Error organizing with AI:", error);
    return NextResponse.json(
      { error: error.message || "Failed to organize notes" },
      { status: 500 }
    );
  }
}
