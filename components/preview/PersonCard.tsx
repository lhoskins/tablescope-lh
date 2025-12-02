import { MapPin, Users } from "lucide-react";

interface PersonCardProps {
  person: {
    name?: string;
    location?: string;
    company?: string;
    role?: string;
    follower_count?: number;
  };
}

export function PersonCard({ person }: PersonCardProps) {
  if (!person) return null;

  return (
    <div className="mb-4">
      <h3 className="text-2xl font-bold text-gray-800 mb-2">{person.name || "Unknown"}</h3>
      {person.location && (
        <p className="text-sm text-gray-600 flex items-center gap-1 mb-1">
          <MapPin className="h-4 w-4" />
          {person.location}
        </p>
      )}
      <p className="text-base text-gray-700 mb-1">
        <span className="font-semibold">{person.company || "Unknown Company"}</span>
      </p>
      <p className="text-sm text-gray-600 mb-2">{person.role || "Unknown Role"}</p>
      {person.follower_count && (
        <p className="text-xs text-gray-500 flex items-center gap-1">
          <Users className="h-3 w-3" />
          {person.follower_count.toLocaleString()} followers
        </p>
      )}
    </div>
  );
}
