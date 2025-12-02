import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { Pinecone } from "@pinecone-database/pinecone";
import OpenAI from "openai";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

const supabase = createClient(supabaseUrl, supabaseServiceKey);

export async function POST(request: Request) {
  try {
    const { rawText, structuredData } = await request.json();

    // Get current user from auth header (you'll need to implement proper auth)
    // For now, we'll use a placeholder
    const userId = "00000000-0000-0000-0000-000000000000"; // TODO: Get from auth

    // 1. Create or get event if mentioned
    let eventId = null;
    if (structuredData.event) {
      const { data: existingEvent } = await supabase
        .from("events")
        .select("id")
        .eq("user_id", userId)
        .eq("name", structuredData.event.name)
        .single();

      if (existingEvent) {
        eventId = existingEvent.id;
      } else {
        const { data: newEvent, error: eventError } = await supabase
          .from("events")
          .insert({
            user_id: userId,
            name: structuredData.event.name,
            date: structuredData.event.date || null,
            location: structuredData.event.location || null,
          })
          .select()
          .single();

        if (eventError) throw eventError;
        eventId = newEvent.id;
      }
    }

    // 2. Create memory
    const { data: memory, error: memoryError } = await supabase
      .from("memories")
      .insert({
        user_id: userId,
        raw_text: rawText,
        source_type: "typed", // or detect from context
        ai_type: structuredData.people?.length > 0 ? "person" : "other",
        event_id: eventId,
        who: structuredData.people?.map((p: any) => p.name).join(", ") || null,
        what: structuredData.summary || null,
        energy_summary: structuredData.summary || null,
        sections: structuredData.sections || [],
        keywords: structuredData.keywords || [],
        companies: structuredData.companies || [],
        industries: structuredData.industries || [],
      })
      .select()
      .single();

    if (memoryError) {
      console.error("❌ Memory insert error:", memoryError);
      throw memoryError;
    }
    console.log("✅ Memory created:", memory.id);

    // 3. Create or update people
    const peopleIds: string[] = [];
    if (structuredData.people) {
      for (const personData of structuredData.people) {
        // Insert person (personal data only)
        const { data: person, error: personError } = await supabase
          .from("people")
          .insert({
            user_id: userId,
            name: personData.name,
            company: personData.company,
            role: personData.role,
            location: personData.location || null,
            linkedin_url: personData.linkedin_url || null,
            company_linkedin_url: personData.company_linkedin_url || null,
            business_needs: personData.business_needs || null,
            opportunities: personData.opportunities || null,
            technologies: personData.technologies || [],
            interests: personData.interests || [],
            skills: personData.skills || [],
            inspiration_level: personData.inspiration_level || null,
            relationship_potential: personData.relationship_potential || null,
            relationship_notes: personData.relationship_notes || null,
          })
          .select()
          .single();

        if (personError) {
          console.error("❌ Person insert error:", personError);
          throw personError;
        }
        console.log("✅ Person created:", person.id, "-", personData.name);
        peopleIds.push(person.id);

        // If we have business profile data (from parsed LinkedIn), save it separately
        if (personData.about || personData.experience || personData.education || personData.follower_count) {
          const { error: businessProfileError } = await supabase
            .from("people_business_profiles")
            .insert({
              person_id: person.id,
              user_id: userId,
              linkedin_url: personData.linkedin_url || null,
              company_linkedin_url: personData.company_linkedin_url || null,
              follower_count: personData.follower_count || null,
              about: personData.about || null,
              experience: personData.experience || null,
              education: personData.education || null,
              current_company: personData.company || null,
              role_title: personData.role || null,
            });

          if (businessProfileError) {
            console.error("Error saving business profile:", businessProfileError);
            // Don't throw - business profile is optional
          }
        }
      }
    }

    // 4. Link memory to people
    if (peopleIds.length > 0) {
      const memoryPeopleLinks = peopleIds.map((personId) => ({
        memory_id: memory.id,
        person_id: personId,
      }));

      const { error: linkError } = await supabase
        .from("memory_people")
        .insert(memoryPeopleLinks);

      if (linkError) {
        console.error("❌ Memory-People link error:", linkError);
        throw linkError;
      }
      console.log("✅ Linked memory to", peopleIds.length, "people");
    }

    // 5. Create follow-ups
    if (structuredData.follow_ups) {
      const followUps = structuredData.follow_ups.map((fu: any) => ({
        user_id: userId,
        person_id: peopleIds[0] || null, // Link to first person if available
        memory_id: memory.id,
        description: fu.description,
        priority: fu.priority || "medium",
        status: "pending",
      }));

      const { error: followUpError } = await supabase
        .from("follow_ups")
        .insert(followUps);

      if (followUpError) {
        console.error("❌ Follow-ups insert error:", followUpError);
        throw followUpError;
      }
      console.log("✅ Created", followUps.length, "follow-ups");
    }

    // 6. Create embedding and save to Pinecone
    if (process.env.PINECONE_API_KEY && process.env.PINECONE_INDEX_NAME) {
      try {
        const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
        const pinecone = new Pinecone({ apiKey: process.env.PINECONE_API_KEY });
        const index = pinecone.index(process.env.PINECONE_INDEX_NAME);

        // Build text to embed: LinkedIn about + experience + user notes
        let textToEmbed = rawText || "";
        
        if (structuredData.people && structuredData.people.length > 0) {
          const person = structuredData.people[0];
          if (person.about) textToEmbed += `\n\nAbout: ${person.about}`;
          if (person.experience) {
            const expText = person.experience.map((exp: any) => 
              `${exp.role} at ${exp.company}: ${exp.description || ''}`
            ).join('\n');
            textToEmbed += `\n\nExperience:\n${expText}`;
          }
        }

        // Create embedding
        const embeddingResponse = await openai.embeddings.create({
          model: "text-embedding-3-large",
          input: textToEmbed,
          dimensions: 1024,
        });

        const embedding = embeddingResponse.data[0].embedding;

        // Prepare metadata
        const metadata: any = {
          memory_id: memory.id,
          user_id: userId,
          summary: structuredData.summary || "",
          sections: structuredData.sections || [],
        };

        if (structuredData.people && structuredData.people.length > 0) {
          const person = structuredData.people[0];
          metadata.person_name = person.name || "";
          metadata.company = person.company || "";
          metadata.role = person.role || "";
          metadata.skills = person.skills || [];
          metadata.technologies = person.technologies || [];
          metadata.interests = person.interests || [];
        }

        // Upsert to Pinecone
        await index.upsert([{
          id: memory.id,
          values: embedding,
          metadata: metadata,
        }]);

        console.log("✅ Saved to Pinecone:", memory.id);
      } catch (pineconeError) {
        console.error("❌ Pinecone error (non-fatal):", pineconeError);
        // Don't throw - Pinecone is optional
      }
    }

    return NextResponse.json({ 
      success: true, 
      memoryId: memory.id,
      peopleCount: peopleIds.length,
      followUpsCount: structuredData.follow_ups?.length || 0,
      eventId: eventId,
      message: "Memory saved successfully!"
    });
  } catch (error: any) {
    console.error("Error saving memory:", error);
    return NextResponse.json(
      { error: error.message || "Failed to save memory" },
      { status: 500 }
    );
  }
}
