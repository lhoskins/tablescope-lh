"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { Mic, Type, Image as ImageIcon, Users, Calendar, CheckSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { AuthButton } from "@/components/AuthButton";

type Section = "all" | "personal" | "business" | "projects" | "relationships" | "todos" | "events" | "trips";

// Extend Window interface for browser speech recognition
declare global {
  interface Window {
    SpeechRecognition: any;
    webkitSpeechRecognition: any;
  }
}

export default function Home() {
  const router = useRouter();
  const [isRecording, setIsRecording] = useState(false);
  const [activeSection, setActiveSection] = useState<Section>("all");
  const [captureText, setCaptureText] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [noteCount, setNoteCount] = useState(0);
  const [isProcessing, setIsProcessing] = useState(false);
  const [aiPreview, setAiPreview] = useState<any>(null);
  const [showRawNotes, setShowRawNotes] = useState(true);
  const [contextType, setContextType] = useState<string>("event"); // event, personal, business, todo, project, trip
  const [persistentEvent, setPersistentEvent] = useState("");
  const [showEventInput, setShowEventInput] = useState(false);
  const [showSessionFields, setShowSessionFields] = useState(false);
  const [sectionName, setSectionName] = useState("");
  const [panelParticipants, setPanelParticipants] = useState("");
  const [linkedInUrls, setLinkedInUrls] = useState("");
  const [companyLinkedInUrls, setCompanyLinkedInUrls] = useState("");
  const [linkedInProfilePaste, setLinkedInProfilePaste] = useState("");
  const [parsedProfileData, setParsedProfileData] = useState<any>(null);
  const [parsedProfilesArray, setParsedProfilesArray] = useState<any[]>([]);
  const [isParsing, setIsParsing] = useState(false);
  const [isParsingUrls, setIsParsingUrls] = useState(false);
  const [isContextExpanded, setIsContextExpanded] = useState(true);
  const [isEditingPreview, setIsEditingPreview] = useState(false);
  const [editedPreview, setEditedPreview] = useState<any>(null);
  const [showLinkedInData, setShowLinkedInData] = useState(false);
  const [showAboutMe, setShowAboutMe] = useState(false);
  const [editedMainNotes, setEditedMainNotes] = useState("");
  const [personName, setPersonName] = useState("");
  const [personCompany, setPersonCompany] = useState("");
  const [personRole, setPersonRole] = useState("");
  const recognitionRef = useRef<any>(null);
  const isProcessingRef = useRef(false);

  // Store the latest transcript
  const [latestTranscript, setLatestTranscript] = useState("");

  // Initialize speech recognition
  useEffect(() => {
    if (typeof window !== "undefined" && !recognitionRef.current) {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      
      if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.continuous = true; // Keep listening
        recognition.interimResults = false;
        recognition.lang = "en-US";

        recognition.onresult = (event: any) => {
          const transcript = event.results[event.results.length - 1][0].transcript;
          if (transcript.trim()) {
            setLatestTranscript(transcript);
          }
        };

        recognition.onerror = (event: any) => {
          console.error("Speech recognition error:", event.error);
          if (event.error !== 'aborted' && event.error !== 'no-speech') {
            alert(`Speech recognition error: ${event.error}`);
          }
          setIsListening(false);
          setIsRecording(false);
        };

        recognition.onend = () => {
          setIsListening(false);
          setIsRecording(false);
        };

        recognitionRef.current = recognition;
      }
    }

    return () => {
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort();
        } catch (e) {
          // Ignore errors on cleanup
        }
      }
    };
  }, []);

  // Handle transcript when it changes
  useEffect(() => {
    if (latestTranscript) {
      // If in preview mode (aiPreview exists), add to My Notes
      if (aiPreview && editedPreview) {
        const notes = editedPreview.additional_notes || [];
        const today = new Date().toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', year: '2-digit' });
        const newNote = {
          date: today,
          text: latestTranscript.trim()
        };
        const newNotes = [newNote, ...notes];
        setEditedPreview({...editedPreview, additional_notes: newNotes});
      } else {
        // Otherwise, add to capture text with date
        const today = new Date().toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', year: '2-digit' });
        const newText = `${today} - ${latestTranscript.trim()}`;
        setCaptureText((prev) => prev ? `${newText}\n${prev}` : newText);
      }
      setLatestTranscript(""); // Clear after processing
    }
  }, [latestTranscript, aiPreview, editedPreview]);

  const handleMicClick = () => {
    if (!recognitionRef.current) {
      alert("Speech recognition is not supported in this browser. Please use Chrome, Safari, or Edge.");
      return;
    }

    if (isListening) {
      // Stop recording
      recognitionRef.current.stop();
      setIsListening(false);
      setIsRecording(false);
    } else {
      // Start recording
      try {
        recognitionRef.current.start();
        setIsListening(true);
        setIsRecording(true);
      } catch (error) {
        console.error("Error starting speech recognition:", error);
      }
    }
  };

  const handleOrganizeWithAI = async () => {
    if (!captureText.trim() && !parsedProfileData && parsedProfilesArray.length === 0) {
      alert("Please add some notes or parse LinkedIn profile(s)!");
      return;
    }

    setIsProcessing(true);
    setShowRawNotes(false);

    try {
      // Call OpenAI API to structure only the user's notes (not LinkedIn data)
      const response = await fetch("/api/organize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          rawText: captureText,
          contextType: contextType,
          persistentEvent: persistentEvent || null,
          sectionName: sectionName || null,
          panelParticipants: panelParticipants || null,
          linkedInUrls: linkedInUrls || null,
          companyLinkedInUrls: companyLinkedInUrls || null,
          parsedProfileData: parsedProfileData, // Single profile
          parsedProfilesArray: parsedProfilesArray.length > 0 ? parsedProfilesArray : null, // Multiple profiles
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to organize notes");
      }

      const data = await response.json();
      setAiPreview(data);
      setEditedPreview(JSON.parse(JSON.stringify(data))); // Set up for editing immediately
      
      // Get the notes without date (date will be displayed separately)
      const rawNotes = captureText.split('---')[1]?.trim() || captureText.split('Add your notes below:')[1]?.trim() || captureText;
      setEditedMainNotes(rawNotes);
      
      setIsEditingPreview(true); // Go straight to edit mode
      setShowRawNotes(false);
    } catch (error) {
      console.error("Error organizing notes:", error);
      alert("Failed to organize notes. Please try again.");
      setShowRawNotes(true);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleDirectSave = async () => {
    setIsProcessing(true);
    try {
      // Build structured data from form fields
      const structuredData = {
        people: [{
          name: personName,
          company: personCompany,
          role: personRole,
          linkedin_url: linkedInUrls,
          company_linkedin_url: companyLinkedInUrls,
        }],
        additional_notes: editedPreview?.additional_notes || [],
        follow_ups: editedPreview?.follow_ups || [],
        context_type: contextType,
      };

      // Save to Supabase
      const response = await fetch("/api/save-memory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rawText: captureText,
          structuredData: structuredData,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to save contact");
      }

      // Clear form and reset
      setCaptureText("");
      setEditedMainNotes("");
      setNoteCount(0);
      setAiPreview(null);
      setShowRawNotes(true);
      setPersonName("");
      setPersonCompany("");
      setPersonRole("");
      setEditedPreview(null);
      setIsEditingPreview(false);
      setLinkedInProfilePaste("");
      setLinkedInUrls("");
      setCompanyLinkedInUrls("");
      alert("Contact saved successfully! Check the Library on the right.");
    } catch (error) {
      console.error("Error saving contact:", error);
      alert("Failed to save contact. Please try again.");
    } finally {
      setIsProcessing(false);
    }
  };

  const handleApproveAndSave = async (dataToSave?: any) => {
    if (!aiPreview) return;

    setIsProcessing(true);
    try {
      // Use provided data or fall back to aiPreview
      const finalData = dataToSave || aiPreview;
      
      // Save to Supabase
      const response = await fetch("/api/save-memory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rawText: editedMainNotes || captureText, // Use edited notes if available
          structuredData: finalData,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to save memory");
      }

      // Clear form and reset
      setCaptureText("");
      setEditedMainNotes("");
      setNoteCount(0);
      setAiPreview(null);
      setShowRawNotes(true);
      setPersonName("");
      setPersonCompany("");
      setPersonRole("");
      setEditedPreview(null);
      setIsEditingPreview(false);
      setLinkedInProfilePaste("");
      setLinkedInUrls("");
      setCompanyLinkedInUrls("");
      alert("Contact saved successfully! Check the Library on the right.");
    } catch (error) {
      console.error("Error saving memory:", error);
      alert("Failed to save memory. Please try again.");
    } finally {
      setIsProcessing(false);
    }
  };

  const handleEditPreview = () => {
    setIsEditingPreview(true);
    setEditedPreview(JSON.parse(JSON.stringify(aiPreview))); // Deep copy
  };

  const handleSavePreviewEdits = () => {
    setAiPreview(editedPreview);
    setIsEditingPreview(false);
  };

  const handleCancelPreviewEdit = () => {
    setIsEditingPreview(false);
    setEditedPreview(null);
  };

  const handleParseLinkedInProfile = async () => {
    if (!linkedInProfilePaste.trim()) {
      alert("Please paste a LinkedIn profile first!");
      return;
    }

    setIsParsing(true);

    try {
      const response = await fetch("/api/parse-linkedin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profileText: linkedInProfilePaste }),
      });

      if (!response.ok) {
        throw new Error("Failed to parse LinkedIn profile");
      }

      const data = await response.json();
      setParsedProfileData(data);
      
      // Auto-fill person info fields
      setPersonName(data.name || "");
      setPersonCompany(data.company || "");
      setPersonRole(data.role || "");
      
      // Clear the paste field
      setLinkedInProfilePaste("");
      
      // Auto-organize with AI to populate background fields
      setIsProcessing(true);
      setIsParsing(false); // Done parsing, now organizing
      
      try {
        // Create a text summary of the LinkedIn profile for AI to process
        const profileSummary = `LinkedIn Profile Data:
Name: ${data.name || 'Unknown'}
Company: ${data.company || 'Unknown'}
Role: ${data.role || 'Unknown'}
${data.follower_count ? `Followers: ${data.follower_count}` : ''}

About: ${data.about || 'No about section'}

Experience:
${data.experience?.map((exp: any) => `- ${exp.role} at ${exp.company} (${exp.dates})`).join('\n') || 'No experience listed'}

Education:
${data.education?.map((edu: any) => `- ${edu.school}${edu.degree ? ` - ${edu.degree}` : ''}`).join('\n') || 'No education listed'}

Skills: ${data.skills?.join(', ') || 'No skills listed'}

${captureText ? `\nAdditional Notes:\n${captureText}` : ''}`;

        const organizeResponse = await fetch("/api/organize", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ 
            rawText: profileSummary,
            contextType: contextType,
            persistentEvent: persistentEvent || null,
            sectionName: sectionName || null,
            panelParticipants: panelParticipants || null,
            linkedInUrls: linkedInUrls || null,
            companyLinkedInUrls: companyLinkedInUrls || null,
            parsedProfileData: data,
            parsedProfilesArray: null,
          }),
        });

        if (!organizeResponse.ok) {
          throw new Error("Failed to organize");
        }

        const organizedData = await organizeResponse.json();
        setAiPreview(organizedData);
        setEditedPreview(JSON.parse(JSON.stringify(organizedData)));
        
        // Initialize empty notes for user to add
        setEditedMainNotes("");
        
        setIsEditingPreview(true);
        setShowRawNotes(false);
        
      } catch (orgError) {
        console.error("Error auto-organizing:", orgError);
        alert("Profile parsed but failed to auto-organize. You can still add notes and organize manually.");
      }
      
    } catch (error) {
      console.error("Error parsing LinkedIn profile:", error);
      alert("Failed to parse LinkedIn profile. Please try again.");
      setIsParsing(false);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleParseLinkedInUrls = async () => {
    const urls = linkedInUrls.split('\n').filter(url => url.trim());
    
    if (urls.length === 0) {
      alert("Please paste LinkedIn URLs (one per line)!");
      return;
    }

    setIsParsingUrls(true);
    const parsedProfiles: any[] = [];

    try {
      for (const url of urls) {
        const response = await fetch("/api/parse-linkedin", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ 
            profileText: `LinkedIn URL: ${url.trim()}`,
            isUrl: true 
          }),
        });

        if (response.ok) {
          const data = await response.json();
          data.linkedin_url = url.trim();
          parsedProfiles.push(data);
        }
      }

      setParsedProfilesArray(parsedProfiles);
      
      const names = parsedProfiles.map(p => p.name || 'Unknown').join(', ');
      alert(`✅ Parsed ${parsedProfiles.length} profiles:\n${names}\n\nAdd your panel notes below, then click "Organize with AI" to save all.`);
      
    } catch (error) {
      console.error("Error parsing LinkedIn URLs:", error);
      alert("Failed to parse some LinkedIn URLs. Please try again.");
    } finally {
      setIsParsingUrls(false);
    }
  };

  const contextTypes = [
    { value: "event", label: "Event/Conference", icon: Calendar },
    { value: "business", label: "Business Meeting", icon: CheckSquare },
    { value: "colleague", label: "Colleague", icon: Users },
    { value: "friends", label: "Friends", icon: Users },
    { value: "family", label: "Family", icon: Users },
  ];

  const sections: { value: Section; label: string }[] = [
    { value: "all", label: "All" },
    { value: "personal", label: "Personal" },
    { value: "business", label: "Business" },
    { value: "projects", label: "Projects" },
    { value: "relationships", label: "Relationships" },
    { value: "todos", label: "ToDos" },
    { value: "events", label: "Events" },
    { value: "trips", label: "Trips" },
  ];

  // Mock data
  const mockPeople = [
    {
      id: 1,
      name: "Sarah Chen",
      company: "FinTech Innovations",
      role: "VP Product",
      tags: ["business", "events"],
      inspiration: "high",
      lastMet: "2 days ago",
    },
    {
      id: 2,
      name: "Marcus Johnson",
      company: "CloudScale AI",
      role: "CTO",
      tags: ["business", "projects"],
      inspiration: "medium",
      lastMet: "1 week ago",
    },
  ];

  const mockEvents = [
    {
      id: 1,
      name: "YC Mixer - SF",
      date: "Nov 28, 2025",
      peopleCount: 5,
      tags: ["business", "events"],
    },
    {
      id: 2,
      name: "Miami Tech Week",
      date: "Nov 15, 2025",
      peopleCount: 12,
      tags: ["business", "trips"],
    },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="border-b border-gray-200 bg-white/80 backdrop-blur-lg">
        <div className="container mx-auto px-4 py-4 flex justify-between items-center">
          <h1 className="text-2xl font-semibold text-gray-800">
            Relationship Builder
          </h1>
          <AuthButton />
        </div>
      </header>

      {/* Main Split Screen */}
      <div className="container mx-auto p-4">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 min-h-[calc(100vh-120px)]">
          {/* Left: Capture Section */}
          <Card className="bg-white border-gray-200 shadow-sm p-6">
            <div className="flex justify-between items-center mb-3">
              <h2 className="text-xl font-semibold text-gray-700">New Entry</h2>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setPersonName("");
                    setPersonCompany("");
                    setPersonRole("");
                    setCaptureText("");
                    setEditedPreview(null);
                    setAiPreview(null);
                    setParsedProfileData(null);
                    setLinkedInProfilePaste("");
                    setLinkedInUrls("");
                    setCompanyLinkedInUrls("");
                    setPersistentEvent("");
                    setSectionName("");
                    setPanelParticipants("");
                  }}
                  className="border-gray-300 bg-white hover:bg-gray-50 text-gray-600"
                >
                  Clear
                </Button>
                {/* Screenshot Upload */}
                <Button
                  variant="outline"
                  size="sm"
                  className="border-gray-300 bg-white hover:bg-gray-50 text-gray-600"
                >
                  <ImageIcon className="mr-2 h-3 w-3" />
                  Choose File
                </Button>
              </div>
            </div>

            {/* Person Info - Always Visible */}
            <div className="mb-3 pb-3 border-b border-gray-200">
              <div className="bg-white p-4 rounded border border-gray-200 space-y-1">
                <input
                  type="text"
                  placeholder="Name"
                  value={personName}
                  onChange={(e) => setPersonName(e.target.value)}
                  className="w-full font-bold text-xl text-gray-800 border-0 p-0 focus:outline-none focus:ring-0 placeholder:text-gray-400"
                />
                <input
                  type="text"
                  placeholder="Company"
                  value={personCompany}
                  onChange={(e) => setPersonCompany(e.target.value)}
                  className="w-full text-sm text-gray-700 border-0 p-0 focus:outline-none focus:ring-0 placeholder:text-gray-400"
                />
                <input
                  type="text"
                  placeholder="Role / Title"
                  value={personRole}
                  onChange={(e) => setPersonRole(e.target.value)}
                  className="w-full text-sm text-gray-700 border-0 p-0 focus:outline-none focus:ring-0 placeholder:text-gray-400"
                />
              </div>
            </div>

            {/* Context Selector & Dynamic Fields */}
            <div className="mb-3 space-y-3 pb-3 border-b border-gray-200">
              {/* Context Type Selector - Always Visible */}
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <CheckSquare className="h-4 w-4 text-gray-500" />
                    <span className="text-sm font-medium text-gray-600">Context</span>
                    <div className="flex flex-nowrap gap-2 ml-2">
                      {contextTypes.map((ctx) => (
                        <Badge
                          key={ctx.value}
                          onClick={() => setContextType(ctx.value)}
                          className={`cursor-pointer transition-colors whitespace-nowrap ${
                            contextType === ctx.value
                              ? "bg-blue-600 text-white hover:bg-blue-700"
                              : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                          }`}
                        >
                          {ctx.label}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  {(contextType === "event" || contextType === "business" || contextType === "colleague" || contextType === "project" || contextType === "trip") && (
                    <button
                      onClick={() => setIsContextExpanded(!isContextExpanded)}
                      className="text-gray-400 text-xs hover:text-gray-600"
                    >
                      {isContextExpanded ? "▼ Hide" : "▶ Show"}
                    </button>
                  )}
                </div>
              </div>

              {/* Collapsible Details Section */}
              {(contextType === "event" || contextType === "business" || contextType === "colleague" || contextType === "project" || contextType === "trip") && (
                <div>

                  {isContextExpanded && (
                    <div className="space-y-3 mt-3">
                      {/* Dynamic Fields Based on Context */}
                      {/* Event Context Fields */}
                      {contextType === "event" && (
                <>
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <Calendar className="h-4 w-4 text-gray-500" />
                      <span className="text-sm font-medium text-gray-600">Event Name</span>
                    </div>
                    <div className="flex gap-2">
                      {!showEventInput && !persistentEvent ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setShowEventInput(true)}
                          className="text-gray-600 border-dashed"
                        >
                          + Set Event
                        </Button>
                      ) : showEventInput ? (
                        <>
                          <input
                            type="text"
                            placeholder="e.g., Tech Summit 2025"
                            value={persistentEvent}
                            onChange={(e) => setPersistentEvent(e.target.value)}
                            className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                            autoFocus
                          />
                          <Button
                            size="sm"
                            onClick={() => setShowEventInput(false)}
                            className="bg-blue-600 hover:bg-blue-700 text-white"
                          >
                            Set
                          </Button>
                        </>
                      ) : (
                        <div className="flex items-center gap-2">
                          <Badge className="bg-blue-100 text-blue-700 px-3 py-1">
                            {persistentEvent}
                          </Badge>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setPersistentEvent("");
                              setShowEventInput(false);
                            }}
                            className="text-gray-500 h-6 px-2"
                          >
                            ✕
                          </Button>
                        </div>
                      )}
                      
                      {!showSessionFields && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setShowSessionFields(true)}
                          className="text-gray-600 border-dashed"
                        >
                          + Set Session
                        </Button>
                      )}
                    </div>
                  </div>
                </>
              )}

              {/* Event-specific fields */}
              {contextType === "event" && (
                <>
                  {/* Session fields - only show when "+ Set Session" is clicked */}
                  {showSessionFields && (
                    <>
                      {/* Section Name */}
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <Type className="h-4 w-4 text-gray-500" />
                            <span className="text-sm font-medium text-gray-600">Session Name</span>
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setShowSessionFields(false);
                              setSectionName("");
                              setPanelParticipants("");
                              setLinkedInUrls("");
                            }}
                            className="text-gray-500 h-6 px-2"
                          >
                            ✕ Remove Session
                          </Button>
                        </div>
                        <input
                          type="text"
                          placeholder="e.g., AI in Healthcare Panel"
                          value={sectionName}
                          onChange={(e) => setSectionName(e.target.value)}
                          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>

                      {/* Panel Participants */}
                      <div>
                        <div className="flex items-center gap-2 mb-2">
                          <Users className="h-4 w-4 text-gray-500" />
                          <span className="text-sm font-medium text-gray-600">Panel Participants</span>
                        </div>
                        <input
                          type="text"
                          placeholder="e.g., Sarah Chen, Mike Johnson, Lisa Park"
                          value={panelParticipants}
                          onChange={(e) => setPanelParticipants(e.target.value)}
                          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>

                      {/* LinkedIn Profile URLs */}
                      <div>
                        <div className="flex items-center gap-2 mb-2">
                          <Users className="h-4 w-4 text-gray-500" />
                          <span className="text-sm font-medium text-gray-600">LinkedIn URLs</span>
                        </div>
                        <textarea
                          placeholder="Paste LinkedIn URLs (one per line) - will be saved for later"
                          value={linkedInUrls}
                          onChange={(e) => setLinkedInUrls(e.target.value)}
                          rows={3}
                          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                        />
                      </div>
                    </>
                  )}

                  {/* 1-on-1 Contact Fields - Only show when session is NOT set */}
                  {!showSessionFields && (
                    <>
                      <div className="space-y-2">
                        {/* Instagram */}
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-medium text-gray-600 w-32">Instagram:</span>
                          <input
                            type="text"
                            placeholder="https://instagram.com/username"
                            className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>
                        
                        {/* Facebook */}
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-medium text-gray-600 w-32">Facebook:</span>
                          <input
                            type="text"
                            placeholder="https://facebook.com/username"
                            className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>
                        
                        {/* TikTok */}
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-medium text-gray-600 w-32">TikTok:</span>
                          <input
                            type="text"
                            placeholder="https://tiktok.com/@username"
                            className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>
                        
                        {/* LinkedIn */}
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-medium text-gray-600 w-32">LinkedIn:</span>
                          <input
                            type="text"
                            placeholder="https://linkedin.com/in/brian-griffin-64065719/"
                            value={linkedInUrls}
                            onChange={(e) => setLinkedInUrls(e.target.value)}
                            className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>
                        
                        {/* LinkedIn Company */}
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-medium text-gray-600 w-32">LinkedIn Company:</span>
                          <input
                            type="text"
                            placeholder="https://linkedin.com/company/example-company/"
                            value={companyLinkedInUrls}
                            onChange={(e) => setCompanyLinkedInUrls(e.target.value)}
                            className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>
                      </div>

                      {/* Paste Entire LinkedIn Profile */}
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <Type className="h-4 w-4 text-gray-500" />
                            <span className="text-sm font-medium text-gray-600">Paste LinkedIn Profile (optional)</span>
                          </div>
                          <Button
                            onClick={handleParseLinkedInProfile}
                            disabled={isParsing || !linkedInProfilePaste.trim()}
                            size="sm"
                            className="bg-green-600 hover:bg-green-700 text-white"
                          >
                            {isParsing ? "Parsing..." : "Parse Profile"}
                          </Button>
                        </div>
                        <textarea
                          placeholder="Copy entire LinkedIn profile and paste here, then click 'Parse Profile' to extract full details..."
                          value={linkedInProfilePaste}
                          onChange={(e) => setLinkedInProfilePaste(e.target.value)}
                          rows={4}
                          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none font-mono text-xs"
                        />
                        <p className="text-xs text-gray-500 mt-1">Desktop: Ctrl+A → Ctrl+C → paste. Mobile: Desktop mode → Select All → Copy</p>
                      </div>
                    </>
                  )}
                </>
              )}

              {/* Business Meeting fields */}
              {contextType === "business" && (
                <>
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <Users className="h-4 w-4 text-gray-500" />
                      <span className="text-sm font-medium text-gray-600">Meeting With</span>
                    </div>
                    <input
                      type="text"
                      placeholder="e.g., Sarah Chen, Mike Johnson"
                      value={panelParticipants}
                      onChange={(e) => setPanelParticipants(e.target.value)}
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <Users className="h-4 w-4 text-gray-500" />
                      <span className="text-sm font-medium text-gray-600">LinkedIn Profile URLs</span>
                    </div>
                    <textarea
                      placeholder="Paste personal LinkedIn profile URLs (one per line)"
                      value={linkedInUrls}
                      onChange={(e) => setLinkedInUrls(e.target.value)}
                      rows={2}
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                    />
                  </div>
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <Users className="h-4 w-4 text-gray-500" />
                      <span className="text-sm font-medium text-gray-600">Company LinkedIn URLs</span>
                    </div>
                    <textarea
                      placeholder="Paste company LinkedIn URLs (one per line)"
                      value={companyLinkedInUrls}
                      onChange={(e) => setCompanyLinkedInUrls(e.target.value)}
                      rows={2}
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                    />
                  </div>

                  {/* Paste Entire LinkedIn Profile */}
                  <div className="border-t border-gray-200 pt-3">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Type className="h-4 w-4 text-gray-500" />
                        <span className="text-sm font-medium text-gray-600">Paste LinkedIn Profile</span>
                      </div>
                      <Button
                        onClick={handleParseLinkedInProfile}
                        disabled={isParsing || !linkedInProfilePaste.trim()}
                        size="sm"
                        className="bg-green-600 hover:bg-green-700 text-white"
                      >
                        {isParsing ? "Parsing..." : "Parse Profile"}
                      </Button>
                    </div>
                    <textarea
                      placeholder="Copy entire LinkedIn profile and paste here, then click 'Parse Profile' to extract information..."
                      value={linkedInProfilePaste}
                      onChange={(e) => setLinkedInProfilePaste(e.target.value)}
                      rows={6}
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none font-mono text-xs"
                    />
                    <p className="text-xs text-gray-500 mt-1">Desktop: Ctrl+A on profile → Ctrl+C → paste. Mobile: Desktop mode → Select All → Copy</p>
                  </div>
                </>
              )}

              {/* Colleague fields */}
              {contextType === "colleague" && (
                <>
                  <div className="space-y-2">
                    {/* Instagram */}
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-medium text-gray-600 w-32">Instagram:</span>
                      <input
                        type="text"
                        placeholder="https://instagram.com/username"
                        className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    
                    {/* Facebook */}
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-medium text-gray-600 w-32">Facebook:</span>
                      <input
                        type="text"
                        placeholder="https://facebook.com/username"
                        className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    
                    {/* TikTok */}
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-medium text-gray-600 w-32">TikTok:</span>
                      <input
                        type="text"
                        placeholder="https://tiktok.com/@username"
                        className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    
                    {/* LinkedIn */}
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-medium text-gray-600 w-32">LinkedIn:</span>
                      <input
                        type="text"
                        placeholder="https://linkedin.com/in/brian-griffin-64065719/"
                        value={linkedInUrls}
                        onChange={(e) => setLinkedInUrls(e.target.value)}
                        className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    
                    {/* LinkedIn Company */}
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-medium text-gray-600 w-32">LinkedIn Company:</span>
                      <input
                        type="text"
                        placeholder="https://linkedin.com/company/example-company/"
                        value={companyLinkedInUrls}
                        onChange={(e) => setCompanyLinkedInUrls(e.target.value)}
                        className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                  </div>

                  {/* Paste Entire LinkedIn Profile */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Type className="h-4 w-4 text-gray-500" />
                        <span className="text-sm font-medium text-gray-600">Paste LinkedIn Profile (optional)</span>
                      </div>
                      <Button
                        onClick={handleParseLinkedInProfile}
                        disabled={isParsing || !linkedInProfilePaste.trim()}
                        size="sm"
                        className="bg-green-600 hover:bg-green-700 text-white"
                      >
                        {isParsing ? "Parsing..." : "Parse Profile"}
                      </Button>
                    </div>
                    <textarea
                      placeholder="Copy entire LinkedIn profile and paste here, then click 'Parse Profile' to extract full details..."
                      value={linkedInProfilePaste}
                      onChange={(e) => setLinkedInProfilePaste(e.target.value)}
                      rows={6}
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none font-mono text-xs"
                    />
                    <p className="text-xs text-gray-500 mt-1">Desktop: Ctrl+A on profile → Ctrl+C → paste. Mobile: Desktop mode → Select All → Copy</p>
                  </div>
                </>
              )}

              {/* Project fields */}
              {contextType === "project" && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <Type className="h-4 w-4 text-gray-500" />
                    <span className="text-sm font-medium text-gray-600">Project Name</span>
                  </div>
                  <input
                    type="text"
                    placeholder="e.g., Website Redesign"
                    value={sectionName}
                    onChange={(e) => setSectionName(e.target.value)}
                    className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              )}

              {/* Trip fields */}
              {contextType === "trip" && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <Calendar className="h-4 w-4 text-gray-500" />
                    <span className="text-sm font-medium text-gray-600">Trip/Destination</span>
                  </div>
                  <input
                    type="text"
                    placeholder="e.g., Tokyo Business Trip"
                    value={persistentEvent}
                    onChange={(e) => setPersistentEvent(e.target.value)}
                    className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              )}
                    </div>
                  )}
                </div>
              )}
            </div>
            
            {/* Voice Recording - Always visible */}
            <div className="mb-3">
              <Button
                onClick={handleMicClick}
                className={`w-full h-16 text-base font-medium transition-all ${
                  isRecording
                    ? "bg-red-100 hover:bg-red-200 text-red-700 animate-pulse"
                    : "bg-blue-50 hover:bg-blue-100 text-blue-700"
                }`}
              >
                <Mic className={`mr-2 h-5 w-5 ${isRecording ? "animate-pulse" : ""}`} />
                {isRecording ? "Recording..." : "Tap to Record"}
              </Button>
              {isRecording && (
                <p className="text-center text-xs text-gray-600 mt-1">
                  Speak naturally...
                </p>
              )}
            </div>

            {/* Conversations - Same format as preview */}
            {showRawNotes && (
              <div className="mb-6">
                <h4 className="font-semibold text-gray-700 mb-2">Conversations</h4>
                <textarea
                  placeholder="Add note (Enter to save, Shift+Enter for new line)"
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm mb-2 resize-none overflow-hidden"
                  rows={1}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey && e.currentTarget.value.trim()) {
                      e.preventDefault();
                      const today = new Date().toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', year: '2-digit' });
                      const newText = `${today} - ${e.currentTarget.value.trim()}`;
                      setCaptureText((prev) => prev ? `${newText}\n\n${prev}` : newText);
                      e.currentTarget.value = '';
                    }
                  }}
                />
                {captureText && (
                  <div className="space-y-2">
                    {captureText.split('\n').filter(line => line.trim()).map((line, idx) => (
                      <div key={idx} className="flex items-center gap-2 p-2 bg-white rounded border border-gray-200">
                        <span className="text-sm text-gray-700 flex-1">{line}</span>
                        <button
                          onClick={() => {
                            const lines = captureText.split('\n').filter(l => l.trim());
                            lines.splice(idx, 1);
                            setCaptureText(lines.join('\n'));
                          }}
                          className="text-red-600 hover:text-red-700 text-xs font-bold"
                        >
                          ×
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {!captureText && (
                  <p className="text-sm text-gray-400 italic">No notes yet</p>
                )}
              </div>
            )}

            {/* Follow-ups - Same in capture mode */}
            {showRawNotes && (
              <div className="mb-6">
                <h4 className="font-semibold text-gray-700 mb-2">Follow-ups</h4>
                <textarea
                  placeholder="Add follow-up action (Enter to save, Shift+Enter for new line)"
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm mb-2 resize-none overflow-hidden"
                  rows={1}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey && e.currentTarget.value.trim()) {
                      e.preventDefault();
                      // Store follow-ups in editedPreview even in capture mode
                      if (!editedPreview) {
                        setEditedPreview({ follow_ups: [{ description: e.currentTarget.value.trim(), priority: 'medium' }] });
                      } else {
                        const followUps = editedPreview.follow_ups || [];
                        const newFollowUps = [...followUps, { description: e.currentTarget.value.trim(), priority: 'medium' }];
                        setEditedPreview({...editedPreview, follow_ups: newFollowUps});
                      }
                      e.currentTarget.value = '';
                    }
                  }}
                />
                {editedPreview?.follow_ups && editedPreview.follow_ups.length > 0 ? (
                  <div className="space-y-2">
                    {editedPreview.follow_ups.map((followUp: any, idx: number) => (
                      <div key={idx} className="flex items-center gap-2 p-2 bg-white rounded border border-gray-200">
                        <span className="text-sm text-gray-700 flex-1">• {followUp.description}</span>
                        <button
                          onClick={() => {
                            const newFollowUps = editedPreview.follow_ups.filter((_: any, i: number) => i !== idx);
                            setEditedPreview({...editedPreview, follow_ups: newFollowUps});
                          }}
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
            )}

            {/* AI Preview */}
            {aiPreview && (
              <div className="mb-6 space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-semibold text-gray-800">Preview</h3>
                </div>

                <Card className="bg-gray-50 border-gray-200 p-4 space-y-2">
                  {isEditingPreview && editedPreview && (
                    // Edit Mode
                    <>
                      {/* LinkedIn Data (Collapsible) */}
                      {editedPreview.people && editedPreview.people.length > 0 && (
                        <div className="bg-white rounded border border-gray-200">
                          <button
                            onClick={() => setShowLinkedInData(!showLinkedInData)}
                            className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-gray-50"
                          >
                            <h4 className="font-semibold text-gray-700">LinkedIn</h4>
                            <span className="text-gray-500">{showLinkedInData ? '▼' : '▶'}</span>
                          </button>
                          {showLinkedInData && (
                          <div className="px-4 pb-4 space-y-3">
                            {/* Keywords */}
                      <div>
                        <h4 className="font-semibold text-gray-700 mb-2">Keywords</h4>
                        <input
                          type="text"
                          placeholder="Add keyword (press Enter)"
                          className="w-full px-3 py-2 border border-gray-300 rounded text-sm mb-2"
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && e.currentTarget.value.trim()) {
                              const newKeywords = [...(editedPreview.keywords || []), e.currentTarget.value.trim()];
                              setEditedPreview({...editedPreview, keywords: newKeywords});
                              e.currentTarget.value = '';
                            }
                          }}
                        />
                        {(editedPreview.keywords && editedPreview.keywords.length > 0) ? (
                          <div className="flex flex-wrap gap-2">
                            {editedPreview.keywords.map((keyword: string, idx: number) => (
                              <Badge 
                                key={idx} 
                                className="bg-blue-100 text-blue-700 text-xs cursor-pointer hover:bg-red-100 hover:text-red-700"
                                onClick={() => {
                                  const newKeywords = editedPreview.keywords.filter((_: any, i: number) => i !== idx);
                                  setEditedPreview({...editedPreview, keywords: newKeywords});
                                }}
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
                            if (e.key === 'Enter' && e.currentTarget.value.trim()) {
                              const newCompanies = [...(editedPreview.companies || []), e.currentTarget.value.trim()];
                              setEditedPreview({...editedPreview, companies: newCompanies});
                              e.currentTarget.value = '';
                            }
                          }}
                        />
                        {(editedPreview.companies && editedPreview.companies.length > 0) ? (
                          <div className="flex flex-wrap gap-2">
                            {editedPreview.companies.map((company: string, idx: number) => (
                              <Badge 
                                key={idx} 
                                className="bg-purple-100 text-purple-700 text-xs cursor-pointer hover:bg-red-100 hover:text-red-700"
                                onClick={() => {
                                  const newCompanies = editedPreview.companies.filter((_: any, i: number) => i !== idx);
                                  setEditedPreview({...editedPreview, companies: newCompanies});
                                }}
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
                            if (e.key === 'Enter' && e.currentTarget.value.trim()) {
                              const newIndustries = [...(editedPreview.industries || []), e.currentTarget.value.trim()];
                              setEditedPreview({...editedPreview, industries: newIndustries});
                              e.currentTarget.value = '';
                            }
                          }}
                        />
                        {(editedPreview.industries && editedPreview.industries.length > 0) ? (
                          <div className="flex flex-wrap gap-2">
                            {editedPreview.industries.map((industry: string, idx: number) => (
                              <Badge 
                                key={idx} 
                                className="bg-green-100 text-green-700 text-xs cursor-pointer hover:bg-red-100 hover:text-red-700"
                                onClick={() => {
                                  const newIndustries = editedPreview.industries.filter((_: any, i: number) => i !== idx);
                                  setEditedPreview({...editedPreview, industries: newIndustries});
                                }}
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
                            if (e.key === 'Enter' && e.currentTarget.value.trim()) {
                              const person = editedPreview.people?.[0];
                              if (person) {
                                const newSkills = [...(person.skills || []), e.currentTarget.value.trim()];
                                const updatedPerson = {...person, skills: newSkills};
                                const updatedPeople = [...(editedPreview.people || [])];
                                updatedPeople[0] = updatedPerson;
                                setEditedPreview({...editedPreview, people: updatedPeople});
                              }
                              e.currentTarget.value = '';
                            }
                          }}
                        />
                        {(editedPreview.people?.[0]?.skills && editedPreview.people[0].skills.length > 0) ? (
                          <div className="flex flex-wrap gap-2">
                            {editedPreview.people[0].skills.map((skill: string, idx: number) => (
                              <Badge 
                                key={idx} 
                                className="bg-amber-100 text-amber-700 text-xs cursor-pointer hover:bg-red-100 hover:text-red-700"
                                onClick={() => {
                                  const person = editedPreview.people[0];
                                  const newSkills = person.skills.filter((_: any, i: number) => i !== idx);
                                  const updatedPerson = {...person, skills: newSkills};
                                  const updatedPeople = [...editedPreview.people];
                                  updatedPeople[0] = updatedPerson;
                                  setEditedPreview({...editedPreview, people: updatedPeople});
                                }}
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
                            if (e.key === 'Enter' && e.currentTarget.value.trim()) {
                              const person = editedPreview.people?.[0];
                              if (person) {
                                const newTechnologies = [...(person.technologies || []), e.currentTarget.value.trim()];
                                const updatedPerson = {...person, technologies: newTechnologies};
                                const updatedPeople = [...(editedPreview.people || [])];
                                updatedPeople[0] = updatedPerson;
                                setEditedPreview({...editedPreview, people: updatedPeople});
                              }
                              e.currentTarget.value = '';
                            }
                          }}
                        />
                        {(editedPreview.people?.[0]?.technologies && editedPreview.people[0].technologies.length > 0) ? (
                          <div className="flex flex-wrap gap-2">
                            {editedPreview.people[0].technologies.map((tech: string, idx: number) => (
                              <Badge 
                                key={idx} 
                                className="bg-cyan-100 text-cyan-700 text-xs cursor-pointer hover:bg-red-100 hover:text-red-700"
                                onClick={() => {
                                  const person = editedPreview.people[0];
                                  const newTechnologies = person.technologies.filter((_: any, i: number) => i !== idx);
                                  const updatedPerson = {...person, technologies: newTechnologies};
                                  const updatedPeople = [...editedPreview.people];
                                  updatedPeople[0] = updatedPerson;
                                  setEditedPreview({...editedPreview, people: updatedPeople});
                                }}
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
                            if (e.key === 'Enter' && e.currentTarget.value.trim()) {
                              const person = editedPreview.people?.[0];
                              if (person) {
                                const newInterests = [...(person.interests || []), e.currentTarget.value.trim()];
                                const updatedPerson = {...person, interests: newInterests};
                                const updatedPeople = [...(editedPreview.people || [])];
                                updatedPeople[0] = updatedPerson;
                                setEditedPreview({...editedPreview, people: updatedPeople});
                              }
                              e.currentTarget.value = '';
                            }
                          }}
                        />
                        {(editedPreview.people?.[0]?.interests && editedPreview.people[0].interests.length > 0) ? (
                          <div className="flex flex-wrap gap-2">
                            {editedPreview.people[0].interests.map((interest: string, idx: number) => (
                              <Badge 
                                key={idx} 
                                className="bg-pink-100 text-pink-700 text-xs cursor-pointer hover:bg-red-100 hover:text-red-700"
                                onClick={() => {
                                  const person = editedPreview.people[0];
                                  const newInterests = person.interests.filter((_: any, i: number) => i !== idx);
                                  const updatedPerson = {...person, interests: newInterests};
                                  const updatedPeople = [...editedPreview.people];
                                  updatedPeople[0] = updatedPerson;
                                  setEditedPreview({...editedPreview, people: updatedPeople});
                                }}
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
                      )}

                      {/* Conversations */}
                      <div>
                        <h4 className="font-semibold text-gray-700 mb-2">Conversations</h4>
                        <textarea
                          placeholder="Add note (Enter to save, Shift+Enter for new line)"
                          className="w-full px-3 py-2 border border-gray-300 rounded text-sm mb-2 resize-none overflow-hidden"
                          rows={1}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey && e.currentTarget.value.trim()) {
                              e.preventDefault();
                              const notes = editedPreview.additional_notes || [];
                              const today = new Date().toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', year: '2-digit' });
                              const newNote = {
                                date: today,
                                text: e.currentTarget.value.trim()
                              };
                              const newNotes = [newNote, ...notes];
                              setEditedPreview({...editedPreview, additional_notes: newNotes});
                              e.currentTarget.value = '';
                            }
                          }}
                        />
                        {editedPreview.additional_notes && editedPreview.additional_notes.length > 0 ? (
                          <div className="space-y-2">
                            {editedPreview.additional_notes.map((note: any, idx: number) => (
                              <div key={idx} className="flex items-center gap-2 p-2 bg-white rounded border border-gray-200">
                                <span className="text-sm text-gray-600 flex-shrink-0">
                                  {note.date || new Date().toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', year: '2-digit' })}
                                </span>
                                <span className="text-sm text-gray-700 flex-1">• {note.text || note}</span>
                                <button
                                  onClick={() => {
                                    const newNotes = editedPreview.additional_notes.filter((_: any, i: number) => i !== idx);
                                    setEditedPreview({...editedPreview, additional_notes: newNotes});
                                  }}
                                  className="text-red-600 hover:text-red-700 text-xs font-bold"
                                >
                                  ×
                                </button>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-sm text-gray-400 italic">No notes yet</p>
                        )}
                      </div>

                      {/* Follow-ups */}
                      <div>
                        <h4 className="font-semibold text-gray-700 mb-2">Follow-ups</h4>
                        <textarea
                          placeholder="Add follow-up action (Enter to save, Shift+Enter for new line)"
                          className="w-full px-3 py-2 border border-gray-300 rounded text-sm mb-2 resize-none overflow-hidden"
                          rows={1}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey && e.currentTarget.value.trim()) {
                              e.preventDefault();
                              const followUps = editedPreview.follow_ups || editedPreview.followUps || [];
                              const newFollowUps = [...followUps, { description: e.currentTarget.value.trim(), priority: 'medium' }];
                              setEditedPreview({...editedPreview, follow_ups: newFollowUps, followUps: undefined});
                              e.currentTarget.value = '';
                            }
                          }}
                        />
                        {((editedPreview.follow_ups || editedPreview.followUps)?.length > 0) ? (
                          <div className="space-y-2">
                            {(editedPreview.follow_ups || editedPreview.followUps).map((followUp: any, idx: number) => (
                              <div key={idx} className="flex items-center gap-2 p-2 bg-white rounded border border-gray-200">
                                <span className="text-sm text-gray-700 flex-1">• {followUp.description}</span>
                                <button
                                  onClick={() => {
                                    const followUps = editedPreview.follow_ups || editedPreview.followUps || [];
                                    const newFollowUps = followUps.filter((_: any, i: number) => i !== idx);
                                    setEditedPreview({...editedPreview, follow_ups: newFollowUps, followUps: undefined});
                                  }}
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

                      <div className="flex gap-2 pt-2">
                        <Button
                          onClick={() => {
                            handleSavePreviewEdits();
                            handleApproveAndSave(editedPreview);
                          }}
                          disabled={isProcessing}
                          className="bg-green-600 hover:bg-green-700 text-white"
                        >
                          {isProcessing ? "Saving..." : "Save to Rolodex"}
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => {
                            setAiPreview(null);
                            setIsEditingPreview(false);
                            setShowRawNotes(true);
                          }}
                        >
                          Cancel
                        </Button>
                      </div>
                    </>
                  )}
                </Card>
              </div>
            )}

            {/* Action Buttons */}
            {!aiPreview && personName.trim() && (
              <div className="flex justify-end">
                <Button 
                  onClick={handleDirectSave}
                  disabled={isProcessing}
                  className="bg-green-600 hover:bg-green-700 text-white font-semibold"
                >
                  {isProcessing ? "Saving..." : "Save to Relationship Builder"}
                </Button>
              </div>
            )}
          </Card>

          {/* Right: Library Section */}
          <Card className="bg-white border-gray-200 shadow-sm p-6">
            <h2 className="text-xl font-semibold mb-4 text-gray-700">Library</h2>

            {/* Section Filter */}
            <div className="mb-6 flex flex-wrap gap-2">
              {sections.map((section) => (
                <Badge
                  key={section.value}
                  variant={activeSection === section.value ? "default" : "outline"}
                  className={`cursor-pointer transition-all ${
                    activeSection === section.value
                      ? "bg-blue-100 hover:bg-blue-200 text-blue-700 border-blue-200"
                      : "border-gray-300 bg-white hover:bg-gray-50 text-gray-600"
                  }`}
                  onClick={() => setActiveSection(section.value)}
                >
                  {section.label}
                </Badge>
              ))}
            </div>

            {/* Tabs */}
            <Tabs defaultValue="people" className="w-full">
              <TabsList className="grid w-full grid-cols-3 bg-gray-100">
                <TabsTrigger value="people" className="data-[state=active]:bg-white data-[state=active]:text-blue-700">
                  <Users className="mr-2 h-4 w-4" />
                  People
                </TabsTrigger>
                <TabsTrigger value="events" className="data-[state=active]:bg-white data-[state=active]:text-blue-700">
                  <Calendar className="mr-2 h-4 w-4" />
                  Events
                </TabsTrigger>
                <TabsTrigger value="followups" className="data-[state=active]:bg-white data-[state=active]:text-blue-700">
                  <CheckSquare className="mr-2 h-4 w-4" />
                  Follow-ups
                </TabsTrigger>
              </TabsList>

              {/* People Tab */}
              <TabsContent value="people" className="space-y-4 mt-4">
                {mockPeople.map((person) => (
                  <Card 
                    key={person.id} 
                    className="bg-white border-gray-200 p-4 hover:bg-gray-50 transition-all cursor-pointer"
                    onClick={() => router.push(`/person/${person.id}`)}
                  >
                    <div className="flex justify-between items-start mb-2">
                      <div>
                        <h3 className="font-semibold text-gray-800">{person.name}</h3>
                        <p className="text-sm text-gray-600">{person.role} at {person.company}</p>
                      </div>
                      <Badge
                        className={
                          person.inspiration === "high"
                            ? "bg-green-100 text-green-700 border-green-200"
                            : person.inspiration === "medium"
                            ? "bg-amber-100 text-amber-700 border-amber-200"
                            : "bg-gray-100 text-gray-700 border-gray-200"
                        }
                      >
                        {person.inspiration === "high" ? "⭐ Inspiring" : "Worth nurturing"}
                      </Badge>
                    </div>
                    <div className="flex gap-2 mb-2">
                      {person.tags.map((tag) => (
                        <Badge key={tag} variant="outline" className="text-xs border-gray-300 text-gray-600">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                    <p className="text-xs text-gray-500">Last met: {person.lastMet}</p>
                  </Card>
                ))}
              </TabsContent>

              {/* Events Tab */}
              <TabsContent value="events" className="space-y-4 mt-4">
                {mockEvents.map((event) => (
                  <Card key={event.id} className="bg-white border-gray-200 p-4 hover:bg-gray-50 transition-all cursor-pointer">
                    <div className="flex justify-between items-start mb-2">
                      <div>
                        <h3 className="font-semibold text-gray-800">{event.name}</h3>
                        <p className="text-sm text-gray-600">{event.date}</p>
                      </div>
                      <Badge className="bg-purple-100 text-purple-700 border-purple-200">{event.peopleCount} people</Badge>
                    </div>
                    <div className="flex gap-2">
                      {event.tags.map((tag) => (
                        <Badge key={tag} variant="outline" className="text-xs border-gray-300 text-gray-600">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  </Card>
                ))}
              </TabsContent>

              {/* Follow-ups Tab */}
              <TabsContent value="followups" className="space-y-4 mt-4">
                <Card className="bg-white border-gray-200 p-4">
                  <div className="flex items-start gap-3">
                    <CheckSquare className="h-5 w-5 text-blue-600 mt-1" />
                    <div className="flex-1">
                      <h3 className="font-semibold text-gray-800 mb-1">Send intro email to Sarah</h3>
                      <p className="text-sm text-gray-600 mb-2">About banking automation partnership</p>
                      <div className="flex gap-2">
                        <Badge className="bg-orange-100 text-orange-700 border-orange-200 text-xs">Due: Next week</Badge>
                        <Badge variant="outline" className="text-xs border-gray-300 text-gray-600">High priority</Badge>
                      </div>
                    </div>
                  </div>
                </Card>
                <Card className="bg-white border-gray-200 p-4">
                  <div className="flex items-start gap-3">
                    <CheckSquare className="h-5 w-5 text-blue-600 mt-1" />
                    <div className="flex-1">
                      <h3 className="font-semibold text-gray-800 mb-1">Follow up with Marcus</h3>
                      <p className="text-sm text-gray-600 mb-2">Share deck about AI infrastructure project</p>
                      <div className="flex gap-2">
                        <Badge className="bg-blue-100 text-blue-700 border-blue-200 text-xs">Due: This week</Badge>
                        <Badge variant="outline" className="text-xs border-gray-300 text-gray-600">Medium priority</Badge>
                      </div>
                    </div>
                  </div>
                </Card>
              </TabsContent>
            </Tabs>
          </Card>
        </div>
      </div>
    </div>
  );
}
