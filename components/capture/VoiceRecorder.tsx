import { Mic } from "lucide-react";
import { Button } from "@/components/ui/button";

interface VoiceRecorderProps {
  isRecording: boolean;
  onToggle: () => void;
}

export function VoiceRecorder({ isRecording, onToggle }: VoiceRecorderProps) {
  return (
    <div className="mb-4">
      <Button
        onClick={onToggle}
        className={`w-full h-16 text-base font-medium transition-all ${
          isRecording
            ? "bg-red-100 hover:bg-red-200 text-red-700 animate-pulse"
            : "bg-blue-600 hover:bg-blue-700 text-white"
        }`}
      >
        <Mic className={`mr-2 h-5 w-5 ${isRecording ? "animate-pulse" : ""}`} />
        {isRecording ? "Recording... (Click to stop)" : "Start Voice Recording"}
      </Button>
    </div>
  );
}
