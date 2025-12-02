"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { AuthButton } from "@/components/AuthButton";
import { CaptureSection } from "@/components/capture/CaptureSection";
import { PreviewSection } from "@/components/preview/PreviewSection";
import { useSpeechRecognition } from "@/hooks/useSpeechRecognition";
import { useAIOrganization } from "@/hooks/useAIOrganization";
import { useMemorySave } from "@/hooks/useMemorySave";

export default function Home() {
  // State
  const [captureText, setCaptureText] = useState("");
  const [linkedInProfilePaste, setLinkedInProfilePaste] = useState("");
  const [parsedProfileData, setParsedProfileData] = useState<any>(null);
  const [isParsing, setIsParsing] = useState(false);

  // Custom hooks
  const { isRecording, toggleListening } = useSpeechRecognition();
  const { isProcessing, aiPreview, organizeWithAI, clearPreview } = useAIOrganization();
  const { isSaving, saveMemory } = useMemorySave();

  // Handle voice recording
  const handleToggleRecording = () => {
    toggleListening((transcript) => {
      setCaptureText((prev) => {
        if (prev.includes('---\nAdd your notes below:')) {
          return prev + "\n" + transcript;
        }
        return prev + (prev ? " " : "") + transcript;
      });
    });
  };

  // Handle LinkedIn profile parsing
  const handleParseLinkedIn = async () => {
    if (!linkedInProfilePaste.trim()) {
      alert("Please paste a LinkedIn profile first!");
      return;
    }

    setIsParsing(true);

    try {
      const response = await fetch("/api/parse-linkedin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profileText: linkedInProfilePaste }),
      });

      if (!response.ok) {
        throw new Error("Failed to parse LinkedIn profile");
      }

      const data = await response.json();
      setParsedProfileData(data);

      const parsedSummary = `✅ Parsed LinkedIn Profile:

Name: ${data.name || 'Unknown'}
Company: ${data.company || 'Unknown'}
Role: ${data.role || 'Unknown'}
${data.follower_count ? `Followers: ${data.follower_count}` : ''}

About:
${data.about || 'No about section'}

Experience:
${data.experience?.map((exp: any) => `• ${exp.role} at ${exp.company} (${exp.dates})`).join('\n') || 'No experience listed'}

Education:
${data.education?.map((edu: any) => `• ${edu.school}${edu.degree ? ` - ${edu.degree}` : ''}`).join('\n') || 'No education listed'}

---
Add your notes below:
`;

      setCaptureText(parsedSummary);
      setLinkedInProfilePaste("");
    } catch (error) {
      console.error("Error parsing LinkedIn profile:", error);
      alert("Failed to parse LinkedIn profile. Please try again.");
    } finally {
      setIsParsing(false);
    }
  };

  // Handle AI organization
  const handleOrganize = async () => {
    const result = await organizeWithAI(
      captureText,
      "personal", // contextType
      "", // persistentEvent
      "", // sectionName
      "", // panelParticipants
      "", // linkedInUrls
      "", // companyLinkedInUrls
      parsedProfileData,
      [] // parsedProfilesArray
    );

    if (result) {
      // Success - preview will show automatically
    }
  };

  // Handle save memory
  const handleSave = async (editedData: any) => {
    try {
      const result = await saveMemory(captureText, editedData);
      
      // Clear form and reset
      setCaptureText("");
      setParsedProfileData(null);
      clearPreview();
      
      alert(`✅ ${result.message}\n\nSaved ${result.peopleCount} person(s) and ${result.followUpsCount} follow-up(s)`);
    } catch (error) {
      alert("Failed to save memory. Please try again.");
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="border-b border-gray-200 bg-white/80 backdrop-blur-lg">
        <div className="container mx-auto px-4 py-4 flex justify-between items-center">
          <h1 className="text-2xl font-semibold text-gray-800">RemindMe</h1>
          <AuthButton />
        </div>
      </header>

      {/* Main Content */}
      <div className="container mx-auto p-4">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 min-h-[calc(100vh-120px)]">
          {/* Left: Capture Section */}
          <Card className="bg-white border-gray-200 shadow-sm p-6">
            <h2 className="text-xl font-semibold text-gray-700 mb-4">Quick Capture</h2>
            
            <CaptureSection
              captureText={captureText}
              onCaptureTextChange={setCaptureText}
              linkedInProfilePaste={linkedInProfilePaste}
              onLinkedInPasteChange={setLinkedInProfilePaste}
              onParseLinkedIn={handleParseLinkedIn}
              isParsing={isParsing}
              isRecording={isRecording}
              onToggleRecording={handleToggleRecording}
              onOrganize={handleOrganize}
              isProcessing={isProcessing}
            />
          </Card>

          {/* Right: Preview Section */}
          <Card className="bg-white border-gray-200 shadow-sm p-6">
            <h2 className="text-xl font-semibold text-gray-700 mb-4">
              {aiPreview ? "Review & Edit" : "Preview"}
            </h2>

            {aiPreview ? (
              <PreviewSection
                captureText={captureText}
                aiPreview={aiPreview}
                onSave={handleSave}
                isSaving={isSaving}
              />
            ) : (
              <div className="flex items-center justify-center h-64 text-gray-400">
                <p className="text-center">
                  Add notes and click "Organize with AI"<br />
                  to see structured preview
                </p>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
