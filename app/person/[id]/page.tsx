"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { createClient } from "@supabase/supabase-js";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { ArrowLeft, Plus, Edit2, Save, X, Calendar, Briefcase, Linkedin } from "lucide-react";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export default function PersonDetailPage() {
  const params = useParams();
  const router = useRouter();
  const personId = params.id as string;

  const [person, setPerson] = useState<any>(null);
  const [businessProfile, setBusinessProfile] = useState<any>(null);
  const [memories, setMemories] = useState<any[]>([]);
  const [expandedMemoryId, setExpandedMemoryId] = useState<string | null>(null);
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [editedSummary, setEditedSummary] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadPersonData();
  }, [personId]);

  const loadPersonData = async () => {
    try {
      const supabase = createClient(supabaseUrl, supabaseAnonKey);

      // Load person
      const { data: personData } = await supabase
        .from("people")
        .select("*")
        .eq("id", personId)
        .single();

      setPerson(personData);

      // Load business profile
      const { data: businessData } = await supabase
        .from("people_business_profiles")
        .select("*")
        .eq("person_id", personId)
        .single();

      setBusinessProfile(businessData);

      // Load memories for this person
      const { data: memoryLinks } = await supabase
        .from("memory_people")
        .select("memory_id")
        .eq("person_id", personId);

      if (memoryLinks && memoryLinks.length > 0) {
        const memoryIds = memoryLinks.map((link) => link.memory_id);
        const { data: memoriesData } = await supabase
          .from("memories")
          .select("*")
          .in("id", memoryIds)
          .order("created_at", { ascending: false });

        setMemories(memoriesData || []);
        
        // Expand most recent memory by default
        if (memoriesData && memoriesData.length > 0) {
          setExpandedMemoryId(memoriesData[0].id);
        }
      }

      setLoading(false);
    } catch (error) {
      console.error("Error loading person data:", error);
      setLoading(false);
    }
  };

  const handleEditMemory = (memory: any) => {
    setEditingMemoryId(memory.id);
    setEditedSummary(memory.summary || "");
  };

  const handleSaveMemory = async (memoryId: string) => {
    try {
      const supabase = createClient(supabaseUrl, supabaseAnonKey);
      
      await supabase
        .from("memories")
        .update({ summary: editedSummary })
        .eq("id", memoryId);

      // Reload memories
      await loadPersonData();
      setEditingMemoryId(null);
    } catch (error) {
      console.error("Error saving memory:", error);
      alert("Failed to save memory");
    }
  };

  const handleCancelEdit = () => {
    setEditingMemoryId(null);
    setEditedSummary("");
  };

  const toggleMemory = (memoryId: string) => {
    setExpandedMemoryId(expandedMemoryId === memoryId ? null : memoryId);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 p-8">
        <div className="max-w-4xl mx-auto">
          <p className="text-gray-600">Loading...</p>
        </div>
      </div>
    );
  }

  if (!person) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 p-8">
        <div className="max-w-4xl mx-auto">
          <p className="text-gray-600">Person not found</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 p-8">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Back Button */}
        <Button
          variant="ghost"
          onClick={() => router.push("/")}
          className="text-gray-600"
        >
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Library
        </Button>

        {/* Person Header Card */}
        <Card className="p-6 bg-white">
          <div className="flex items-start justify-between">
            <div className="flex-1">
              <h1 className="text-2xl font-bold text-gray-800 mb-2">
                {person.name || "Unknown"}
              </h1>
              
              {person.company && (
                <div className="flex items-center gap-2 text-gray-600 mb-2">
                  <Briefcase className="h-4 w-4" />
                  <span>{person.role} at {person.company}</span>
                </div>
              )}

              {person.linkedin_url && (
                <a
                  href={person.linkedin_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 text-blue-600 hover:text-blue-700 text-sm"
                >
                  <Linkedin className="h-4 w-4" />
                  View LinkedIn Profile
                </a>
              )}

              {/* Business Profile Info */}
              {businessProfile && (
                <div className="mt-4 pt-4 border-t border-gray-200">
                  {businessProfile.about && (
                    <div className="mb-3">
                      <h3 className="text-sm font-semibold text-gray-700 mb-1">About</h3>
                      <p className="text-sm text-gray-600 line-clamp-3">
                        {businessProfile.about}
                      </p>
                    </div>
                  )}
                  
                  {businessProfile.follower_count && (
                    <p className="text-sm text-gray-500">
                      {businessProfile.follower_count.toLocaleString()} LinkedIn followers
                    </p>
                  )}
                </div>
              )}

              {/* Tags */}
              <div className="flex flex-wrap gap-2 mt-3">
                {person.inspiration_level && (
                  <Badge className="bg-purple-100 text-purple-700">
                    Inspiration: {person.inspiration_level}
                  </Badge>
                )}
                {person.relationship_potential && person.relationship_potential !== "no" && (
                  <Badge className="bg-green-100 text-green-700">
                    Relationship: {person.relationship_potential}
                  </Badge>
                )}
              </div>
            </div>

            <Button
              onClick={() => router.push(`/?person=${personId}`)}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              <Plus className="h-4 w-4 mr-2" />
              Add Memory
            </Button>
          </div>
        </Card>

        {/* Memory Timeline */}
        <div className="space-y-4">
          <h2 className="text-xl font-semibold text-gray-800">
            Memory Timeline ({memories.length})
          </h2>

          {memories.length === 0 ? (
            <Card className="p-8 text-center bg-white">
              <p className="text-gray-500 mb-4">No memories yet</p>
              <Button
                onClick={() => router.push(`/?person=${personId}`)}
                className="bg-blue-600 hover:bg-blue-700 text-white"
              >
                <Plus className="h-4 w-4 mr-2" />
                Add First Memory
              </Button>
            </Card>
          ) : (
            memories.map((memory, index) => {
              const isExpanded = expandedMemoryId === memory.id;
              const isEditing = editingMemoryId === memory.id;
              const isRecent = index === 0;

              return (
                <Card
                  key={memory.id}
                  className={`p-4 bg-white cursor-pointer transition-all ${
                    isRecent ? "border-2 border-blue-500" : ""
                  }`}
                  onClick={() => !isEditing && toggleMemory(memory.id)}
                >
                  {/* Memory Header */}
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <Calendar className="h-4 w-4 text-gray-500" />
                      <span className="text-sm font-medium text-gray-700">
                        {new Date(memory.created_at).toLocaleDateString("en-US", {
                          month: "short",
                          day: "numeric",
                          year: "numeric",
                        })}
                      </span>
                      {isRecent && (
                        <Badge className="bg-blue-100 text-blue-700 text-xs">
                          Most Recent
                        </Badge>
                      )}
                    </div>

                    {isExpanded && !isEditing && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleEditMemory(memory);
                        }}
                        className="text-gray-600"
                      >
                        <Edit2 className="h-4 w-4" />
                      </Button>
                    )}
                  </div>

                  {/* Memory Content */}
                  {isExpanded ? (
                    <div className="space-y-3 mt-4">
                      {isEditing ? (
                        <>
                          <Textarea
                            value={editedSummary}
                            onChange={(e) => setEditedSummary(e.target.value)}
                            className="min-h-[100px]"
                            onClick={(e) => e.stopPropagation()}
                          />
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleSaveMemory(memory.id);
                              }}
                              className="bg-green-600 hover:bg-green-700 text-white"
                            >
                              <Save className="h-4 w-4 mr-2" />
                              Save
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleCancelEdit();
                              }}
                            >
                              <X className="h-4 w-4 mr-2" />
                              Cancel
                            </Button>
                          </div>
                        </>
                      ) : (
                        <>
                          <p className="text-gray-700 whitespace-pre-wrap">
                            {memory.summary || "No summary"}
                          </p>
                          
                          {memory.sections && memory.sections.length > 0 && (
                            <div className="flex flex-wrap gap-2 pt-2">
                              {memory.sections.map((section: string) => (
                                <Badge
                                  key={section}
                                  className="bg-gray-100 text-gray-600 text-xs"
                                >
                                  {section}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  ) : (
                    <p className="text-sm text-gray-600 line-clamp-2">
                      {memory.summary || "No summary"}
                    </p>
                  )}
                </Card>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
