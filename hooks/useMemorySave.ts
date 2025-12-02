import { useState } from "react";

export function useMemorySave() {
  const [isSaving, setIsSaving] = useState(false);

  const saveMemory = async (rawText: string, structuredData: any) => {
    setIsSaving(true);
    try {
      const response = await fetch("/api/save-memory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rawText: rawText,
          structuredData: structuredData,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to save memory");
      }

      const result = await response.json();
      return result;
    } catch (error) {
      console.error("Error saving memory:", error);
      throw error;
    } finally {
      setIsSaving(false);
    }
  };

  return {
    isSaving,
    saveMemory,
  };
}
