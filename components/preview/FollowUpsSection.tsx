import { Badge } from "@/components/ui/badge";

interface FollowUpsSectionProps {
  editedPreview: any;
  setEditedPreview: (preview: any) => void;
}

export function FollowUpsSection({ editedPreview, setEditedPreview }: FollowUpsSectionProps) {
  const addFollowUp = (description: string) => {
    const followUps = editedPreview.follow_ups || editedPreview.followUps || [];
    const newFollowUps = [
      ...followUps,
      { description, priority: "medium", status: "pending" },
    ];
    setEditedPreview({ ...editedPreview, follow_ups: newFollowUps });
  };

  const removeFollowUp = (index: number) => {
    const followUps = editedPreview.follow_ups || editedPreview.followUps || [];
    const newFollowUps = followUps.filter((_: any, i: number) => i !== index);
    setEditedPreview({ ...editedPreview, follow_ups: newFollowUps });
  };

  const followUps = editedPreview.follow_ups || editedPreview.followUps || [];

  return (
    <div>
      <h4 className="font-semibold text-gray-700 mb-2">Follow-ups</h4>
      <input
        type="text"
        placeholder="Add follow-up action (press Enter)"
        className="w-full px-3 py-2 border border-gray-300 rounded text-sm mb-2"
        onKeyDown={(e) => {
          if (e.key === "Enter" && e.currentTarget.value.trim()) {
            addFollowUp(e.currentTarget.value.trim());
            e.currentTarget.value = "";
          }
        }}
      />
      {followUps.length > 0 ? (
        <div className="space-y-2">
          {followUps.map((followUp: any, idx: number) => (
            <div
              key={idx}
              className="flex items-center gap-2 p-2 bg-white border border-gray-200 rounded"
            >
              <span className="flex-1 text-sm">• {followUp.description}</span>
              <Badge
                variant="outline"
                className="text-xs border-gray-300 text-gray-600"
              >
                {followUp.priority || "medium"}
              </Badge>
              <button
                onClick={() => removeFollowUp(idx)}
                className="text-red-600 hover:text-red-700 text-xs font-bold"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-400 italic">No follow-ups yet</p>
      )}
    </div>
  );
}
