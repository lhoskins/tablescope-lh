import { ChevronDown, ChevronUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface BackgroundSectionProps {
  editedPreview: any;
  setEditedPreview: (preview: any) => void;
  isExpanded: boolean;
  onToggle: () => void;
}

export function BackgroundSection({
  editedPreview,
  setEditedPreview,
  isExpanded,
  onToggle,
}: BackgroundSectionProps) {
  const addKeyword = (keyword: string) => {
    const newKeywords = [...(editedPreview.keywords || []), keyword];
    setEditedPreview({ ...editedPreview, keywords: newKeywords });
  };

  const removeKeyword = (index: number) => {
    const newKeywords = editedPreview.keywords.filter((_: any, i: number) => i !== index);
    setEditedPreview({ ...editedPreview, keywords: newKeywords });
  };

  const addCompany = (company: string) => {
    const newCompanies = [...(editedPreview.companies || []), company];
    setEditedPreview({ ...editedPreview, companies: newCompanies });
  };

  const removeCompany = (index: number) => {
    const newCompanies = editedPreview.companies.filter((_: any, i: number) => i !== index);
    setEditedPreview({ ...editedPreview, companies: newCompanies });
  };

  const addIndustry = (industry: string) => {
    const newIndustries = [...(editedPreview.industries || []), industry];
    setEditedPreview({ ...editedPreview, industries: newIndustries });
  };

  const removeIndustry = (index: number) => {
    const newIndustries = editedPreview.industries.filter((_: any, i: number) => i !== index);
    setEditedPreview({ ...editedPreview, industries: newIndustries });
  };

  const addSkill = (skill: string) => {
    const person = editedPreview.people?.[0];
    if (person) {
      const newSkills = [...(person.skills || []), skill];
      const updatedPerson = { ...person, skills: newSkills };
      const updatedPeople = [...(editedPreview.people || [])];
      updatedPeople[0] = updatedPerson;
      setEditedPreview({ ...editedPreview, people: updatedPeople });
    }
  };

  const removeSkill = (index: number) => {
    const person = editedPreview.people[0];
    const newSkills = person.skills.filter((_: any, i: number) => i !== index);
    const updatedPerson = { ...person, skills: newSkills };
    const updatedPeople = [...editedPreview.people];
    updatedPeople[0] = updatedPerson;
    setEditedPreview({ ...editedPreview, people: updatedPeople });
  };

  const addTechnology = (tech: string) => {
    const person = editedPreview.people?.[0];
    if (person) {
      const newTechnologies = [...(person.technologies || []), tech];
      const updatedPerson = { ...person, technologies: newTechnologies };
      const updatedPeople = [...(editedPreview.people || [])];
      updatedPeople[0] = updatedPerson;
      setEditedPreview({ ...editedPreview, people: updatedPeople });
    }
  };

  const removeTechnology = (index: number) => {
    const person = editedPreview.people[0];
    const newTechnologies = person.technologies.filter((_: any, i: number) => i !== index);
    const updatedPerson = { ...person, technologies: newTechnologies };
    const updatedPeople = [...editedPreview.people];
    updatedPeople[0] = updatedPerson;
    setEditedPreview({ ...editedPreview, people: updatedPeople });
  };

  const addInterest = (interest: string) => {
    const person = editedPreview.people?.[0];
    if (person) {
      const newInterests = [...(person.interests || []), interest];
      const updatedPerson = { ...person, interests: newInterests };
      const updatedPeople = [...(editedPreview.people || [])];
      updatedPeople[0] = updatedPerson;
      setEditedPreview({ ...editedPreview, people: updatedPeople });
    }
  };

  const removeInterest = (index: number) => {
    const person = editedPreview.people[0];
    const newInterests = person.interests.filter((_: any, i: number) => i !== index);
    const updatedPerson = { ...person, interests: newInterests };
    const updatedPeople = [...editedPreview.people];
    updatedPeople[0] = updatedPerson;
    setEditedPreview({ ...editedPreview, people: updatedPeople });
  };

  return (
    <div className="mb-4">
      <button
        onClick={onToggle}
        className="flex items-center justify-between w-full text-left mb-2 hover:bg-gray-50 p-2 rounded transition-colors"
      >
        <h4 className="font-semibold text-gray-700">Background</h4>
        {isExpanded ? (
          <ChevronUp className="h-4 w-4 text-gray-500" />
        ) : (
          <ChevronDown className="h-4 w-4 text-gray-500" />
        )}
      </button>

      {isExpanded && (
        <div className="space-y-4 bg-gray-50 p-4 rounded border border-gray-200">
          {/* Keywords */}
          <div>
            <h4 className="font-semibold text-gray-700 mb-2">Keywords</h4>
            <input
              type="text"
              placeholder="Add keyword (press Enter)"
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm mb-2"
              onKeyDown={(e) => {
                if (e.key === "Enter" && e.currentTarget.value.trim()) {
                  addKeyword(e.currentTarget.value.trim());
                  e.currentTarget.value = "";
                }
              }}
            />
            {editedPreview.keywords && editedPreview.keywords.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {editedPreview.keywords.map((keyword: string, idx: number) => (
                  <Badge
                    key={idx}
                    className="bg-blue-100 text-blue-700 text-xs cursor-pointer hover:bg-red-100 hover:text-red-700"
                    onClick={() => removeKeyword(idx)}
                  >
                    {keyword} ×
                  </Badge>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-400 italic">No keywords yet</p>
            )}
          </div>

          {/* Companies */}
          <div>
            <h4 className="font-semibold text-gray-700 mb-2">Companies</h4>
            <input
              type="text"
              placeholder="Add company (press Enter)"
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm mb-2"
              onKeyDown={(e) => {
                if (e.key === "Enter" && e.currentTarget.value.trim()) {
                  addCompany(e.currentTarget.value.trim());
                  e.currentTarget.value = "";
                }
              }}
            />
            {editedPreview.companies && editedPreview.companies.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {editedPreview.companies.map((company: string, idx: number) => (
                  <Badge
                    key={idx}
                    className="bg-purple-100 text-purple-700 text-xs cursor-pointer hover:bg-red-100 hover:text-red-700"
                    onClick={() => removeCompany(idx)}
                  >
                    {company} ×
                  </Badge>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-400 italic">No companies yet</p>
            )}
          </div>

          {/* Industries */}
          <div>
            <h4 className="font-semibold text-gray-700 mb-2">Industries</h4>
            <input
              type="text"
              placeholder="Add industry (press Enter)"
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm mb-2"
              onKeyDown={(e) => {
                if (e.key === "Enter" && e.currentTarget.value.trim()) {
                  addIndustry(e.currentTarget.value.trim());
                  e.currentTarget.value = "";
                }
              }}
            />
            {editedPreview.industries && editedPreview.industries.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {editedPreview.industries.map((industry: string, idx: number) => (
                  <Badge
                    key={idx}
                    className="bg-green-100 text-green-700 text-xs cursor-pointer hover:bg-red-100 hover:text-red-700"
                    onClick={() => removeIndustry(idx)}
                  >
                    {industry} ×
                  </Badge>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-400 italic">No industries yet</p>
            )}
          </div>

          {/* Skills */}
          <div>
            <h4 className="font-semibold text-gray-700 mb-2">Skills</h4>
            <input
              type="text"
              placeholder="Add skill (press Enter)"
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm mb-2"
              onKeyDown={(e) => {
                if (e.key === "Enter" && e.currentTarget.value.trim()) {
                  addSkill(e.currentTarget.value.trim());
                  e.currentTarget.value = "";
                }
              }}
            />
            {editedPreview.people?.[0]?.skills && editedPreview.people[0].skills.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {editedPreview.people[0].skills.map((skill: string, idx: number) => (
                  <Badge
                    key={idx}
                    className="bg-amber-100 text-amber-700 text-xs cursor-pointer hover:bg-red-100 hover:text-red-700"
                    onClick={() => removeSkill(idx)}
                  >
                    {skill} ×
                  </Badge>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-400 italic">No skills yet</p>
            )}
          </div>

          {/* Technologies */}
          <div>
            <h4 className="font-semibold text-gray-700 mb-2">Technologies</h4>
            <input
              type="text"
              placeholder="Add technology (press Enter)"
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm mb-2"
              onKeyDown={(e) => {
                if (e.key === "Enter" && e.currentTarget.value.trim()) {
                  addTechnology(e.currentTarget.value.trim());
                  e.currentTarget.value = "";
                }
              }}
            />
            {editedPreview.people?.[0]?.technologies && editedPreview.people[0].technologies.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {editedPreview.people[0].technologies.map((tech: string, idx: number) => (
                  <Badge
                    key={idx}
                    className="bg-cyan-100 text-cyan-700 text-xs cursor-pointer hover:bg-red-100 hover:text-red-700"
                    onClick={() => removeTechnology(idx)}
                  >
                    {tech} ×
                  </Badge>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-400 italic">No technologies yet</p>
            )}
          </div>

          {/* Interests */}
          <div>
            <h4 className="font-semibold text-gray-700 mb-2">Interests</h4>
            <input
              type="text"
              placeholder="Add interest (press Enter)"
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm mb-2"
              onKeyDown={(e) => {
                if (e.key === "Enter" && e.currentTarget.value.trim()) {
                  addInterest(e.currentTarget.value.trim());
                  e.currentTarget.value = "";
                }
              }}
            />
            {editedPreview.people?.[0]?.interests && editedPreview.people[0].interests.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {editedPreview.people[0].interests.map((interest: string, idx: number) => (
                  <Badge
                    key={idx}
                    className="bg-pink-100 text-pink-700 text-xs cursor-pointer hover:bg-red-100 hover:text-red-700"
                    onClick={() => removeInterest(idx)}
                  >
                    {interest} ×
                  </Badge>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-400 italic">No interests yet</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
