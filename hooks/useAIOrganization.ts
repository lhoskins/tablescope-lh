import { useState } from "react";

export function useAIOrganization() {
  const [isProcessing, setIsProcessing] = useState(false);
  const [aiPreview, setAiPreview] = useState<any>(null);

  const organizeWithAI = async (
    captureText: string,
    contextType: string,
    persistentEvent: string,
    sectionName: string,
    panelParticipants: string,
    linkedInUrls: string,
    companyLinkedInUrls: string,
    parsedProfileData: any,
    parsedProfilesArray: any[]
  ) => {
    if (!captureText.trim() && !parsedProfileData && parsedProfilesArray.length === 0) {
      alert("Please add some notes or parse LinkedIn profile(s)!");
      return null;
    }

    setIsProcessing(true);

    try {
      const response = await fetch("/api/organize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rawText: captureText,
          contextType: contextType,
          persistentEvent: persistentEvent || null,
          sectionName: sectionName || null,
          panelParticipants: panelParticipants || null,
          linkedInUrls: linkedInUrls || null,
          companyLinkedInUrls: companyLinkedInUrls || null,
          parsedProfileData: parsedProfileData,
          parsedProfilesArray: parsedProfilesArray.length > 0 ? parsedProfilesArray : null,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to organize notes");
      }

      const data = await response.json();
      setAiPreview(data);
      return data;
    } catch (error) {
      console.error("Error organizing notes:", error);
      alert("Failed to organize notes. Please try again.");
      return null;
    } finally {
      setIsProcessing(false);
    }
  };

  const clearPreview = () => {
    setAiPreview(null);
  };

  return {
    isProcessing,
    aiPreview,
    organizeWithAI,
    clearPreview,
    setAiPreview,
  };
}
