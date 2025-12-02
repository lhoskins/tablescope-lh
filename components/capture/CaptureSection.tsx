import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { VoiceRecorder } from "./VoiceRecorder";
import { LinkedInPasteInput } from "./LinkedInPasteInput";

interface CaptureSectionProps {
  captureText: string;
  onCaptureTextChange: (text: string) => void;
  linkedInProfilePaste: string;
  onLinkedInPasteChange: (text: string) => void;
  onParseLinkedIn: () => void;
  isParsing: boolean;
  isRecording: boolean;
  onToggleRecording: () => void;
  onOrganize: () => void;
  isProcessing: boolean;
}

export function CaptureSection({
  captureText,
  onCaptureTextChange,
  linkedInProfilePaste,
  onLinkedInPasteChange,
  onParseLinkedIn,
  isParsing,
  isRecording,
  onToggleRecording,
  onOrganize,
  isProcessing,
}: CaptureSectionProps) {
  return (
    <div className="space-y-4">
      {/* Voice Recording */}
      <VoiceRecorder isRecording={isRecording} onToggle={onToggleRecording} />

      {/* Text Input */}
      <div>
        <label className="block text-sm font-medium text-gray-600 mb-2">
          Your Notes
        </label>
        <Textarea
          placeholder="Type or speak your notes about the person you met..."
          value={captureText}
          onChange={(e) => onCaptureTextChange(e.target.value)}
          rows={8}
          className="w-full resize-none"
        />
        <p className="text-xs text-gray-500 mt-1">
          Will be saved to database
        </p>
      </div>

      {/* LinkedIn Profile Paste */}
      <LinkedInPasteInput
        value={linkedInProfilePaste}
        onChange={onLinkedInPasteChange}
        onParse={onParseLinkedIn}
        isParsing={isParsing}
      />

      {/* Organize Button */}
      <Button
        onClick={onOrganize}
        disabled={isProcessing || (!captureText.trim() && !linkedInProfilePaste.trim())}
        className="w-full bg-purple-600 hover:bg-purple-700 text-white font-medium py-3"
      >
        <Sparkles className="mr-2 h-5 w-5" />
        {isProcessing ? "Organizing..." : "Organize with AI"}
      </Button>
    </div>
  );
}
