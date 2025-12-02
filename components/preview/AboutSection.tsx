import { ChevronDown, ChevronUp } from "lucide-react";

interface AboutSectionProps {
  about?: string;
  isExpanded: boolean;
  onToggle: () => void;
}

export function AboutSection({ about, isExpanded, onToggle }: AboutSectionProps) {
  if (!about) return null;

  return (
    <div className="mb-4">
      <button
        onClick={onToggle}
        className="flex items-center justify-between w-full text-left mb-2 hover:bg-gray-50 p-2 rounded transition-colors"
      >
        <h4 className="font-semibold text-gray-700">About me</h4>
        {isExpanded ? (
          <ChevronUp className="h-4 w-4 text-gray-500" />
        ) : (
          <ChevronDown className="h-4 w-4 text-gray-500" />
        )}
      </button>
      {isExpanded && (
        <div className="bg-gray-50 p-3 rounded border border-gray-200">
          <p className="text-sm text-gray-700 whitespace-pre-wrap">{about}</p>
        </div>
      )}
    </div>
  );
}
