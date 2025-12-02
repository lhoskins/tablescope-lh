import { useState } from "react";
import { Button } from "@/components/ui/button";
import { PersonCard } from "./PersonCard";
import { AboutSection } from "./AboutSection";
import { BackgroundSection } from "./BackgroundSection";
import { NotesSection } from "./NotesSection";
import { FollowUpsSection } from "./FollowUpsSection";

interface PreviewSectionProps {
  captureText: string;
  aiPreview: any;
  onSave: (editedData: any) => void;
  isSaving: boolean;
}

export function PreviewSection({ captureText, aiPreview, onSave, isSaving }: PreviewSectionProps) {
  const [editedPreview, setEditedPreview] = useState(aiPreview);
  const [showAboutMe, setShowAboutMe] = useState(false);
  const [showBackground, setShowBackground] = useState(false);

  const handleSave = () => {
    onSave(editedPreview);
  };

  if (!aiPreview) return null;

  const person = editedPreview.people?.[0];

  return (
    <div className="space-y-4">
      {/* Person Card */}
      {person && <PersonCard person={person} />}

      {/* About Me Section */}
      {person?.about && (
        <AboutSection
          about={person.about}
          isExpanded={showAboutMe}
          onToggle={() => setShowAboutMe(!showAboutMe)}
        />
      )}

      {/* Background Section */}
      <BackgroundSection
        editedPreview={editedPreview}
        setEditedPreview={setEditedPreview}
        isExpanded={showBackground}
        onToggle={() => setShowBackground(!showBackground)}
      />

      {/* My Notes */}
      <NotesSection
        captureText={captureText}
        editedPreview={editedPreview}
        setEditedPreview={setEditedPreview}
      />

      {/* Follow-ups */}
      <FollowUpsSection
        editedPreview={editedPreview}
        setEditedPreview={setEditedPreview}
      />

      {/* Save Button */}
      <Button
        onClick={handleSave}
        disabled={isSaving}
        className="w-full bg-green-600 hover:bg-green-700 text-white font-medium py-3"
      >
        {isSaving ? "Saving..." : "Add Memory"}
      </Button>
    </div>
  );
}
