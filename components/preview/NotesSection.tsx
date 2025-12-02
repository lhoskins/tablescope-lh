interface NotesSectionProps {
  captureText: string;
  editedPreview: any;
  setEditedPreview: (preview: any) => void;
}

export function NotesSection({ captureText, editedPreview, setEditedPreview }: NotesSectionProps) {
  const addNote = (note: string) => {
    const notes = editedPreview.additional_notes || [];
    const newNotes = [...notes, note];
    setEditedPreview({ ...editedPreview, additional_notes: newNotes });
  };

  const removeNote = (index: number) => {
    const newNotes = editedPreview.additional_notes.filter((_: any, i: number) => i !== index);
    setEditedPreview({ ...editedPreview, additional_notes: newNotes });
  };

  const displayText = captureText.split('---')[1]?.trim() || 
                      captureText.split('Add your notes below:')[1]?.trim() || 
                      captureText;

  return (
    <div>
      <h4 className="font-semibold text-gray-700 mb-2">My Notes</h4>
      <input
        type="text"
        placeholder="Add additional note (press Enter)"
        className="w-full px-3 py-2 border border-gray-300 rounded text-sm mb-2"
        onKeyDown={(e) => {
          if (e.key === "Enter" && e.currentTarget.value.trim()) {
            addNote(e.currentTarget.value.trim());
            e.currentTarget.value = "";
          }
        }}
      />
      <div className="bg-white p-3 rounded border border-gray-200 text-sm text-gray-700 space-y-2">
        <div className="whitespace-pre-wrap">{displayText}</div>
        {editedPreview.additional_notes && editedPreview.additional_notes.length > 0 && (
          <div className="space-y-2 mt-3 pt-3 border-t border-gray-200">
            {editedPreview.additional_notes.map((note: string, idx: number) => (
              <div key={idx} className="flex items-center gap-2 p-2 bg-gray-50 rounded">
                <span className="flex-1">• {note}</span>
                <button
                  onClick={() => removeNote(idx)}
                  className="text-red-600 hover:text-red-700 text-xs font-bold"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
