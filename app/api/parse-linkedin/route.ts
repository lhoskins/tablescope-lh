import { NextResponse } from "next/server";
import OpenAI from "openai";

const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
});

export async function POST(request: Request) {
  try {
    const { profileText } = await request.json();

    if (!profileText) {
      return NextResponse.json(
        { error: "No profile text provided" },
        { status: 400 }
      );
    }

    const completion = await openai.chat.completions.create({
      model: "gpt-4o-mini",
      messages: [
        {
          role: "system",
          content: `You are a LinkedIn profile parser. Extract structured information from the pasted LinkedIn profile text.

Extract and return JSON with:
- name: Full name
- company: Current company
- role: Current job title
- about: About/summary section
- experience: Array of work history with {company, role, dates, description}
- education: Array of education with {school, degree, dates}
- skills: Array of skills mentioned
- follower_count: Number of followers if mentioned

Return ONLY valid JSON, no additional text.`,
        },
        {
          role: "user",
          content: profileText,
        },
      ],
      response_format: { type: "json_object" },
      temperature: 0.3,
    });

    const result = completion.choices[0].message.content;
    const parsedData = JSON.parse(result || "{}");

    return NextResponse.json(parsedData);

  } catch (error: any) {
    console.error("Error parsing LinkedIn profile:", error);
    return NextResponse.json(
      { error: error.message || "Failed to parse LinkedIn profile" },
      { status: 500 }
    );
  }
}
