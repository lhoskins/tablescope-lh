import { Type } from "lucide-react";
import { Button } from "@/components/ui/button";

interface LinkedInPasteInputProps {
  value: string;
  onChange: (value: string) => void;
  onParse: () => void;
  isParsing: boolean;
}

export function LinkedInPasteInput({
  value,
  onChange,
  onParse,
  isParsing,
}: LinkedInPasteInputProps) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Type className="h-4 w-4 text-gray-500" />
          <span className="text-sm font-medium text-gray-600">
            Paste LinkedIn Profile (optional)
          </span>
        </div>
        <Button
          onClick={onParse}
          disabled={isParsing || !value.trim()}
          size="sm"
          className="bg-green-600 hover:bg-green-700 text-white"
        >
          {isParsing ? "Parsing..." : "Parse Profile"}
        </Button>
      </div>
      <textarea
        placeholder="Copy entire LinkedIn profile and paste here, then click 'Parse Profile' to extract full details..."
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={4}
        className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none font-mono text-xs"
      />
      <p className="text-xs text-gray-500 mt-1">
        Desktop: Ctrl+A → Ctrl+C → paste. Mobile: Desktop mode → Select All → Copy
      </p>
    </div>
  );
}
