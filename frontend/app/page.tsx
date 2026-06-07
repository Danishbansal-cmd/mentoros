"use client";

import { useState, useEffect, useRef } from "react";
import Auth from "./components/Auth";

interface Task {
  _id: string;
  title: string;
  description: string;
  estimatedHours: number;
  difficulty: "beginner" | "intermediate" | "advanced";
  status: "pending" | "completed" | "in_progress";
  prerequisites: string[];
  resources: string[];
  projects: string[];
  quizIds: string[];
  notes: string;
}

interface ChatMessage {
  role: "user" | "model";
  content: string;
  timestamp: string;
}

interface Roadmap {
  id: string;
  goal: string;
  roadmap: Task[];
  createdAt: string;
  progress: {
    completed: number;
    total: number;
  };
  chatHistory?: ChatMessage[];
}

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [roadmaps, setRoadmaps] = useState<Roadmap[]>([]);
  const [activeRoadmap, setActiveRoadmap] = useState<Roadmap | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isGeneratingMode, setIsGeneratingMode] = useState(false);

  // Chat panel states
  const [chatMessageValue, setChatMessageValue] = useState("");
  const [isChatLoading, setIsChatLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  // Collapsible task card states
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [notesText, setNotesText] = useState<{ [taskId: string]: string }>({});
  const [isSavingNotes, setIsSavingNotes] = useState<{ [taskId: string]: boolean }>({});

  // Load auth state on mount
  useEffect(() => {
    const savedToken = localStorage.getItem("token");
    const savedUsername = localStorage.getItem("username");
    if (savedToken && savedUsername) {
      setToken(savedToken);
      setUsername(savedUsername);
      fetchRoadmaps(savedToken);
    }
  }, []);

  const handleAuthSuccess = (newToken: string, newUsername: string) => {
    setToken(newToken);
    setUsername(newUsername);
    fetchRoadmaps(newToken);
  };

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    setToken(null);
    setUsername(null);
    setRoadmaps([]);
    setActiveRoadmap(null);
    setIsGeneratingMode(false);
    setError(null);
  };

  const fetchRoadmaps = async (authToken: string) => {
    try {
      const res = await fetch("http://127.0.0.1:8000/roadmaps", {
        headers: {
          Authorization: `Bearer ${authToken}`,
        },
      });
      if (res.status === 401) {
        handleLogout();
        return;
      }
      if (!res.ok) throw new Error("Failed to load roadmaps.");
      const data = await res.json();
      setRoadmaps(data);
      if (data.length > 0) {
        // If there's an active roadmap selected, keep it, otherwise select the latest
        setActiveRoadmap((prev) => {
          if (prev) {
            const updated = data.find((r: Roadmap) => r.id === prev.id);
            return updated || data[0];
          }
          return data[0];
        });
      } else {
        setIsGeneratingMode(true);
      }
    } catch (err: any) {
      setError(err.message || "Error fetching roadmaps.");
    }
  };

  const handleGenerateRoadmap = async () => {
    if (!inputValue.trim() || !token) return;

    setIsLoading(true);
    setError(null);

    try {
      const res = await fetch("http://127.0.0.1:8000/generate-roadmap", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ goal: inputValue }),
      });

      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || "Failed to generate roadmap.");
      }

      // Refresh roadmaps to grab the newly generated one
      await fetchRoadmaps(token);
      setInputValue("");
      setIsGeneratingMode(false);
    } catch (err: any) {
      setError(err.message || "Could not generate roadmap.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleToggleTaskStatus = async (roadmapId: string, taskId: string, currentStatus: string) => {
    if (!token) return;

    const newStatus = currentStatus === "completed" ? "pending" : "completed";

    // Optimistically update frontend state
    const originalActiveRoadmap = activeRoadmap;
    const originalRoadmaps = roadmaps;

    // Local update
    if (activeRoadmap && activeRoadmap.id === roadmapId) {
      const currentActive = activeRoadmap;
      const updatedTasks = currentActive.roadmap.map((t) =>
        t._id === taskId ? { ...t, status: newStatus as "pending" | "completed" | "in_progress" } : t
      );
      const completedCount = updatedTasks.filter((t) => t.status === "completed").length;
      
      const updatedRoadmap: Roadmap = {
        id: currentActive.id,
        goal: currentActive.goal,
        roadmap: updatedTasks,
        createdAt: currentActive.createdAt,
        progress: {
          completed: completedCount,
          total: currentActive.progress.total,
        },
        chatHistory: currentActive.chatHistory,
      };
      
      setActiveRoadmap(updatedRoadmap);
      setRoadmaps((prev) =>
        prev.map((r) => (r.id === roadmapId ? updatedRoadmap : r))
      );
    }

    try {
      const res = await fetch(`http://127.0.0.1:8000/roadmaps/${roadmapId}/tasks/${taskId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ status: newStatus }),
      });

      if (!res.ok) {
        throw new Error("Failed to update status on server.");
      }
    } catch (err) {
      console.error(err);
      // Revert states on error
      setActiveRoadmap(originalActiveRoadmap);
      setRoadmaps(originalRoadmaps);
      setError("Failed to sync task update with server.");
    }
  };

  const handleSaveNotes = async (roadmapId: string, taskId: string) => {
    if (!token) return;

    const taskNotes = notesText[taskId] || "";
    setIsSavingNotes((prev) => ({ ...prev, [taskId]: true }));

    try {
      const res = await fetch(`http://127.0.0.1:8000/roadmaps/${roadmapId}/tasks/${taskId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ notes: taskNotes }),
      });

      if (!res.ok) {
        throw new Error("Failed to save notes to server.");
      }

      // Update activeRoadmap local state with the new notes
      if (activeRoadmap) {
        const currentActive = activeRoadmap;
        const updatedTasks = currentActive.roadmap.map((t) =>
          t._id === taskId ? { ...t, notes: taskNotes } : t
        );
        const updatedRoadmap: Roadmap = {
          id: currentActive.id,
          goal: currentActive.goal,
          roadmap: updatedTasks,
          createdAt: currentActive.createdAt,
          progress: currentActive.progress,
          chatHistory: currentActive.chatHistory,
        };
        setActiveRoadmap(updatedRoadmap);
        setRoadmaps((prev) =>
          prev.map((r) => (r.id === roadmapId ? updatedRoadmap : r))
        );
      }
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Failed to save notes.");
    } finally {
      setIsSavingNotes((prev) => ({ ...prev, [taskId]: false }));
    }
  };

  // Scroll to bottom of chat history when messages or loading state changes
  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [activeRoadmap?.chatHistory, isChatLoading]);

  const handleSendChatMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatMessageValue.trim() || !token || !activeRoadmap || isChatLoading) return;

    const message = chatMessageValue.trim();
    setChatMessageValue("");
    setIsChatLoading(true);
    setError(null);

    // Optimistically update chat history in frontend state
    const optimisticMessage: ChatMessage = {
      role: "user",
      content: message,
      timestamp: new Date().toISOString(),
    };
    
    const originalActiveRoadmap = activeRoadmap;
    const originalRoadmaps = roadmaps;

    const currentActive = activeRoadmap;
    if (!currentActive) return;

    const updatedHistory = [...(currentActive.chatHistory || []), optimisticMessage];
    const updatedRoadmap: Roadmap = {
      id: currentActive.id,
      goal: currentActive.goal,
      roadmap: currentActive.roadmap,
      createdAt: currentActive.createdAt,
      progress: currentActive.progress,
      chatHistory: updatedHistory,
    };

    setActiveRoadmap(updatedRoadmap);
    setRoadmaps((prev) =>
      prev.map((r) => (r.id === currentActive.id ? updatedRoadmap : r))
    );

    try {
      const res = await fetch(`http://127.0.0.1:8000/roadmaps/${currentActive.id}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ message }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to get response from AI mentor.");
      }

      const data = await res.json();
      // data contains: { response: string, roadmap: Task[], chatHistory: ChatMessage[] }
      
      const serverUpdatedRoadmap: Roadmap = {
        id: currentActive.id,
        goal: currentActive.goal,
        roadmap: data.roadmap,
        createdAt: currentActive.createdAt,
        progress: {
          completed: data.roadmap.filter((t: Task) => t.status === "completed").length,
          total: data.roadmap.length,
        },
        chatHistory: data.chatHistory,
      };

      setActiveRoadmap(serverUpdatedRoadmap);
      setRoadmaps((prev) =>
        prev.map((r) => (r.id === currentActive.id ? serverUpdatedRoadmap : r))
      );
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Failed to communicate with AI mentor.");
      setActiveRoadmap(originalActiveRoadmap);
      setRoadmaps(originalRoadmaps);
    } finally {
      setIsChatLoading(false);
    }
  };

  // If not logged in, show Auth landing page
  if (!token) {
    return (
      <div className="relative flex min-h-screen items-center justify-center bg-slate-950 px-4 py-12 text-slate-100 selection:bg-indigo-500/30">
        {/* Decorative Grid Lines */}
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#0f172a_1px,transparent_1px),linear-gradient(to_bottom,#0f172a_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_50%,#000_70%,transparent_100%)]"></div>
        <Auth onAuthSuccess={handleAuthSuccess} />
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 font-sans overflow-hidden">
      {/* SIDEBAR */}
      <aside className="w-80 border-r border-slate-900 bg-slate-900/40 backdrop-blur-md flex flex-col justify-between shrink-0">
        <div className="flex flex-col flex-1 min-h-0">
          {/* Logo / Header */}
          <div className="p-6 border-b border-slate-900/80 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-500 to-violet-500 text-lg font-black text-white shadow-md shadow-indigo-500/20">
              M
            </div>
            <div>
              <h1 className="font-bold text-lg leading-none tracking-tight">MentorOS</h1>
              <span className="text-[10px] text-indigo-400 font-semibold tracking-wider uppercase">AI Core</span>
            </div>
          </div>

          {/* New Roadmap Trigger */}
          <div className="p-4">
            <button
              onClick={() => {
                setIsGeneratingMode(true);
                setError(null);
              }}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 py-3 text-sm font-semibold transition duration-200 active:scale-[0.98] shadow-lg shadow-indigo-600/15"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              New Learning Goal
            </button>
          </div>

          {/* Roadmap List */}
          <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-2">
            <h2 className="px-2 mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">My roadmaps</h2>
            {roadmaps.length === 0 ? (
              <p className="text-sm text-slate-500 px-2 italic">No goals created yet.</p>
            ) : (
              roadmaps.map((r) => {
                const isActive = activeRoadmap?.id === r.id && !isGeneratingMode;
                const completed = r.progress?.completed || 0;
                const total = r.progress?.total || r.roadmap.length || 1;
                const percentage = Math.round((completed / total) * 100);

                return (
                  <button
                    key={r.id}
                    onClick={() => {
                      setActiveRoadmap(r);
                      setIsGeneratingMode(false);
                      setError(null);
                    }}
                    className={`w-full text-left p-3.5 rounded-2xl border transition duration-200 group relative ${
                      isActive
                        ? "bg-slate-900 border-indigo-500/50 text-white shadow-lg shadow-indigo-500/5"
                        : "bg-slate-900/40 border-transparent hover:bg-slate-900/60 hover:border-slate-800 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <p className="font-semibold text-sm line-clamp-1 pr-4">{r.goal}</p>
                    
                    <div className="mt-2.5 flex items-center justify-between text-[11px] font-medium text-slate-500 group-hover:text-slate-400">
                      <span>{percentage}% completed</span>
                      <span>{completed}/{total} tasks</span>
                    </div>

                    {/* Simple progress bar */}
                    <div className="mt-1.5 h-1 w-full bg-slate-950 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-indigo-500 transition-all duration-300"
                        style={{ width: `${percentage}%` }}
                      ></div>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* User Card & Logout */}
        <div className="p-4 border-t border-slate-900 bg-slate-900/20 flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <div className="h-9 w-9 rounded-full bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center font-bold text-indigo-400 shrink-0 uppercase">
              {username?.charAt(0)}
            </div>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-slate-400 leading-none">Logged in as</p>
              <p className="text-sm font-bold text-white truncate mt-0.5">{username}</p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-rose-400 hover:border-rose-500/30 transition duration-150"
            title="Log Out"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M19 12H9m10 0l-3-3m3 3l-3 3" />
            </svg>
          </button>
        </div>
      </aside>

      {/* MAIN CONTENT WORKSPACE */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden relative">
        {/* Grid mask for subtle tech style in workspace */}
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#0c111d_1px,transparent_1px),linear-gradient(to_bottom,#0c111d_1px,transparent_1px)] bg-[size:3rem_3rem] pointer-events-none opacity-20"></div>

        {/* Top Navbar */}
        <header className="h-20 border-b border-slate-900 px-8 flex items-center justify-between shrink-0 bg-slate-950/80 backdrop-blur-md z-10">
          <div className="min-w-0">
            {isGeneratingMode ? (
              <h2 className="text-lg font-bold text-white">Create New Roadmap</h2>
            ) : activeRoadmap ? (
              <h2 className="text-lg font-bold text-white truncate">{activeRoadmap.goal}</h2>
            ) : (
              <h2 className="text-lg font-bold text-white">Select a Learning Path</h2>
            )}
          </div>
          
          {error && (
            <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 px-4 py-2 rounded-xl text-xs flex items-center gap-2">
              <span>⚠️ {error}</span>
              <button onClick={() => setError(null)} className="font-bold text-[10px] uppercase ml-1 opacity-70 hover:opacity-100">Dismiss</button>
            </div>
          )}
        </header>

        {/* Main Body */}
        <div className="flex-1 overflow-y-auto p-8 z-10">
          {/* GENERATE ROADMAP MODE */}
          {isGeneratingMode ? (
            <div className="max-w-2xl mx-auto my-8">
              <div className="bg-slate-900/60 border border-slate-900 rounded-3xl p-8 backdrop-blur-sm relative">
                <h3 className="text-xl font-bold text-white mb-2">What skills do you want to master?</h3>
                <p className="text-sm text-slate-400 mb-6">Describe your learning goals, background, or time frame. Our AI mentor will craft a step-by-step roadmap specifically for you.</p>

                <div className="space-y-4">
                  <textarea
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    placeholder="e.g. Master React and Next.js in 30 days to build web apps, starting with zero experience."
                    className="w-full h-32 rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-white placeholder-slate-600 outline-none transition duration-200 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50 resize-none text-sm"
                    disabled={isLoading}
                  />

                  {/* Suggestion Prompts */}
                  <div className="flex flex-wrap gap-2 pt-1">
                    {[
                      "Backend Dev (Python) in 60 days",
                      "Machine Learning foundations",
                      "TypeScript & Advanced React",
                      "System Design interviews",
                    ].map((s, idx) => (
                      <button
                        key={idx}
                        onClick={() => setInputValue(s)}
                        disabled={isLoading}
                        className="text-xs bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:border-slate-700 px-3 py-1.5 rounded-full transition"
                      >
                        {s}
                      </button>
                    ))}
                  </div>

                  <div className="pt-4 flex gap-3">
                    <button
                      onClick={handleGenerateRoadmap}
                      disabled={isLoading || !inputValue.trim()}
                      className="flex-1 rounded-2xl bg-indigo-600 hover:bg-indigo-500 py-3.5 text-sm font-semibold text-white shadow-lg shadow-indigo-600/20 transition duration-200 active:scale-[0.98] disabled:opacity-40"
                    >
                      {isLoading ? (
                        <span className="flex items-center justify-center gap-2">
                          <svg className="h-4 w-4 animate-spin text-white" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                          </svg>
                          Generating Roadmap via Gemini...
                        </span>
                      ) : (
                        "Generate Personalized Path"
                      )}
                    </button>
                    {roadmaps.length > 0 && (
                      <button
                        onClick={() => setIsGeneratingMode(false)}
                        disabled={isLoading}
                        className="rounded-2xl border border-slate-800 bg-slate-900/20 hover:bg-slate-900/60 px-6 py-3.5 text-sm font-semibold text-slate-400 hover:text-white transition duration-200"
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ) : activeRoadmap ? (
            /* ACTIVE ROADMAP DETAIL VIEW WITH CHAT PANEL side-by-side */
            <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-5 gap-8 items-start">
              {/* Left Column: Roadmap milestones */}
              <div className="lg:col-span-3 space-y-6">
                {/* Analytics Header card */}
                <div className="bg-gradient-to-r from-indigo-950/40 to-slate-900/40 border border-slate-900 rounded-3xl p-6 flex flex-col sm:flex-row justify-between items-center gap-6">
                  <div>
                    <h3 className="text-xl font-extrabold text-white">Goal Progress Profile</h3>
                    <p className="text-sm text-slate-400 mt-1 max-w-xl">
                      Mark tasks complete as you work your way through each milestone. Checkmarks are synced instantly.
                    </p>
                  </div>
                  
                  {/* Visual completion badge */}
                  <div className="flex items-center gap-4 shrink-0 bg-slate-900 border border-slate-800 px-6 py-4 rounded-2xl">
                    <div className="relative flex items-center justify-center">
                      <svg className="h-14 w-14 transform -rotate-90">
                        <circle cx="28" cy="28" r="24" className="stroke-slate-800" strokeWidth="4" fill="transparent" />
                        <circle
                          cx="28"
                          cy="28"
                          r="24"
                          className="stroke-indigo-500"
                          strokeWidth="4"
                          fill="transparent"
                          strokeDasharray={2 * Math.PI * 24}
                          strokeDashoffset={
                            2 * Math.PI * 24 * (1 - (activeRoadmap.progress?.completed || 0) / (activeRoadmap.progress?.total || activeRoadmap.roadmap.length || 1))
                          }
                        />
                      </svg>
                      <span className="absolute text-xs font-black text-indigo-400">
                        {Math.round(((activeRoadmap.progress?.completed || 0) / (activeRoadmap.progress?.total || activeRoadmap.roadmap.length || 1)) * 100)}%
                      </span>
                    </div>
                    <div>
                      <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">Completed</p>
                      <p className="text-lg font-black text-white leading-none mt-1">
                        {activeRoadmap.progress?.completed || 0} <span className="text-sm text-slate-500 font-normal">/ {activeRoadmap.progress?.total || activeRoadmap.roadmap.length}</span>
                      </p>
                    </div>
                  </div>
                </div>

                {/* Tasks List */}
                <div className="space-y-4">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Milestones & Tasks</h4>
                  <div className="grid gap-4">
                    {activeRoadmap.roadmap.map((item, idx) => {
                      const isCompleted = item.status === "completed";
                      const isExpanded = expandedTaskId === item._id;

                      // Choose color for difficulty badge
                      let difficultyColor = "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
                      if (item.difficulty === "intermediate") {
                        difficultyColor = "text-amber-400 bg-amber-500/10 border-amber-500/20";
                      } else if (item.difficulty === "advanced") {
                        difficultyColor = "text-rose-400 bg-rose-500/10 border-rose-500/20";
                      }

                      return (
                        <div
                          key={item._id}
                          className={`rounded-2xl border transition-all duration-200 overflow-hidden ${
                            isCompleted
                              ? "bg-slate-900/30 border-indigo-950/40 text-slate-400"
                              : "bg-slate-900/60 border-slate-900 text-slate-100 hover:border-slate-800"
                          }`}
                        >
                          {/* Header section (Always visible) */}
                          <div 
                            className="flex items-start gap-4 p-5 cursor-pointer select-none"
                            onClick={() => {
                              if (isExpanded) {
                                setExpandedTaskId(null);
                              } else {
                                setExpandedTaskId(item._id);
                                if (notesText[item._id] === undefined) {
                                  setNotesText((prev) => ({ ...prev, [item._id]: item.notes || "" }));
                                }
                              }
                            }}
                          >
                            {/* Interactive checkbox */}
                            <button
                              onClick={(e) => {
                                e.stopPropagation(); // Prevent toggling expansion
                                handleToggleTaskStatus(activeRoadmap.id, item._id, item.status);
                              }}
                              className={`mt-1 shrink-0 flex h-6 w-6 items-center justify-center rounded-lg border transition ${
                                isCompleted
                                  ? "bg-indigo-500 border-indigo-500 text-white"
                                  : "border-slate-700 bg-slate-950 hover:border-indigo-500/50"
                              }`}
                            >
                              {isCompleted && (
                                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="3">
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                                </svg>
                              )}
                            </button>

                            <div className="flex-1 min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="text-[10px] font-bold uppercase text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20">
                                  Milestone {idx + 1}
                                </span>
                                <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${difficultyColor}`}>
                                  {item.difficulty}
                                </span>
                                <span className="text-[10px] font-medium text-slate-400 bg-slate-950/60 px-2 py-0.5 rounded-full border border-slate-800 flex items-center gap-1">
                                  ⏱️ {item.estimatedHours}h
                                </span>
                              </div>
                              
                              <p className={`font-bold text-sm mt-2 leading-snug truncate ${isCompleted ? "line-through text-slate-500" : "text-white"}`}>
                                {item.title}
                              </p>
                            </div>

                            {/* Chevron expand indicator */}
                            <div className="text-slate-500 hover:text-slate-300 mt-1.5 shrink-0 transition-transform duration-200" style={{ transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                              </svg>
                            </div>
                          </div>

                          {/* Expanded section details */}
                          {isExpanded && (
                            <div className="px-5 pb-5 pt-1 border-t border-slate-900/60 bg-slate-950/25 space-y-4 text-xs">
                              {/* Long description */}
                              <div>
                                <h5 className="font-bold text-slate-500 uppercase tracking-wider text-[10px] mb-1">Detailed Description</h5>
                                <p className="text-slate-300 leading-relaxed whitespace-pre-line">{item.description}</p>
                              </div>

                              {/* Prerequisites (if any) */}
                              {item.prerequisites && item.prerequisites.length > 0 && (
                                <div>
                                  <h5 className="font-bold text-slate-500 uppercase tracking-wider text-[10px] mb-1">Prerequisites</h5>
                                  <div className="flex flex-wrap gap-1.5 mt-1">
                                    {item.prerequisites.map((prereq, pidx) => (
                                      <span key={pidx} className="px-2 py-0.5 bg-slate-900 border border-slate-800/80 rounded-md text-slate-400">
                                        🔑 {prereq}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}

                              {/* Resources (if any) */}
                              {item.resources && item.resources.length > 0 && (
                                <div>
                                  <h5 className="font-bold text-slate-500 uppercase tracking-wider text-[10px] mb-1">Recommended Resources</h5>
                                  <ul className="space-y-1 mt-1 text-slate-400 list-disc list-inside">
                                    {item.resources.map((res, ridx) => (
                                      <li key={ridx} className="hover:text-indigo-400 transition truncate">
                                        {res.startsWith("http") ? (
                                          <a href={res} target="_blank" rel="noopener noreferrer" className="underline decoration-indigo-500/40">
                                            {res}
                                          </a>
                                        ) : (
                                          <span>📚 {res}</span>
                                        )}
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}

                              {/* Projects (if any) */}
                              {item.projects && item.projects.length > 0 && (
                                <div>
                                  <h5 className="font-bold text-slate-500 uppercase tracking-wider text-[10px] mb-1">Hands-on Exercises / Mini Projects</h5>
                                  <ul className="space-y-1 mt-1 text-slate-300">
                                    {item.projects.map((proj, pridx) => (
                                      <li key={pridx} className="flex items-start gap-1.5 leading-relaxed text-slate-400">
                                        <span className="text-indigo-500">⚡</span>
                                        <span>{proj}</span>
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}

                              {/* Notes section */}
                              <div className="pt-2 border-t border-slate-900/60">
                                <div className="flex items-center justify-between mb-1.5">
                                  <h5 className="font-bold text-slate-500 uppercase tracking-wider text-[10px]">My Study Notes</h5>
                                  {isSavingNotes[item._id] && (
                                    <span className="text-[10px] text-indigo-400 flex items-center gap-1 animate-pulse">
                                      Saving...
                                    </span>
                                  )}
                                </div>
                                <textarea
                                  value={notesText[item._id] ?? ""}
                                  onChange={(e) => setNotesText((prev) => ({ ...prev, [item._id]: e.target.value }))}
                                  placeholder="Add your study logs, commands, links or progress notes here..."
                                  className="w-full h-24 p-3 bg-slate-950/60 border border-slate-800 rounded-xl text-slate-300 placeholder-slate-650 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50 outline-none resize-none"
                                />
                                <div className="flex justify-end mt-2">
                                  <button
                                    onClick={() => handleSaveNotes(activeRoadmap.id, item._id)}
                                    disabled={isSavingNotes[item._id]}
                                    className="px-3 py-1.5 text-[10px] font-bold bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition active:scale-[0.98] disabled:opacity-50 shadow-md shadow-indigo-650/15"
                                  >
                                    Save Notes
                                  </button>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Right Column: AI Learning Mentor Chat */}
              <div className="lg:col-span-2 lg:sticky lg:top-8 bg-slate-900/40 border border-slate-900 rounded-3xl p-6 backdrop-blur-sm flex flex-col h-[600px] relative overflow-hidden shadow-xl shadow-indigo-950/5">
                {/* Chat Header */}
                <div className="flex items-center justify-between border-b border-slate-900/80 pb-4 mb-4">
                  <div className="flex items-center gap-2">
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
                    </span>
                    <h3 className="font-bold text-sm text-white">AI Learning Mentor</h3>
                  </div>
                  <span className="text-[10px] text-indigo-400 font-medium bg-indigo-950/50 px-2 py-0.5 rounded-full border border-indigo-900/30">
                    Gemini 2.5 Active
                  </span>
                </div>

                {/* Messages List */}
                <div className="flex-1 overflow-y-auto space-y-4 pr-1 mb-4 scrollbar-thin scrollbar-thumb-slate-800">
                  {activeRoadmap.chatHistory && activeRoadmap.chatHistory.map((msg, index) => {
                    const isUser = msg.role === "user";
                    return (
                      <div key={index} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                        <div
                          className={`max-w-[85%] rounded-2xl p-4 text-sm leading-relaxed ${
                            isUser
                              ? "bg-indigo-600 text-white rounded-br-none"
                              : "bg-slate-900 border border-slate-800 text-slate-300 rounded-bl-none"
                          }`}
                        >
                          <p className="whitespace-pre-line">{msg.content}</p>
                          <span className={`block text-[10px] mt-1.5 ${isUser ? "text-indigo-200" : "text-slate-500"}`}>
                            {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                  {isChatLoading && (
                    <div className="flex justify-start">
                      <div className="bg-slate-900 border border-slate-800 text-slate-400 rounded-2xl rounded-bl-none p-4 text-sm flex items-center gap-2">
                        <svg className="animate-spin h-4 w-4 text-indigo-400" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                        </svg>
                        <span>Mentor is processing...</span>
                      </div>
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>

                {/* Input Form */}
                <form onSubmit={handleSendChatMessage} className="flex gap-2">
                  <input
                    type="text"
                    value={chatMessageValue}
                    onChange={(e) => setChatMessageValue(e.target.value)}
                    placeholder="Modify roadmap or ask questions..."
                    className="flex-1 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm text-white placeholder-slate-600 outline-none transition focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50"
                    disabled={isChatLoading}
                  />
                  <button
                    type="submit"
                    disabled={isChatLoading || !chatMessageValue.trim()}
                    className="rounded-xl bg-indigo-600 hover:bg-indigo-500 px-4 py-3 text-white transition disabled:opacity-40 flex items-center justify-center shrink-0 active:scale-[0.98] shadow-md shadow-indigo-600/10"
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
                    </svg>
                  </button>
                </form>
              </div>
            </div>
          ) : (
            /* EMPTY STATE */
            <div className="flex flex-col items-center justify-center text-center h-full max-w-md mx-auto">
              <div className="h-16 w-16 bg-slate-900 border border-slate-800 rounded-3xl flex items-center justify-center text-slate-500 mb-6">
                <svg className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.375c.9 0 1.625-.724 1.625-1.625 0-.901-.725-1.625-1.625-1.625H9m1.5-4.875L18 10.5m-3.75 9h-3.75" />
                </svg>
              </div>
              <h3 className="text-xl font-bold text-white mb-2">No learning paths found</h3>
              <p className="text-sm text-slate-500 mb-6">Create a goal now to generate your first learning path customized by Gemini.</p>
              <button
                onClick={() => setIsGeneratingMode(true)}
                className="rounded-2xl bg-indigo-600 hover:bg-indigo-500 px-6 py-3 text-sm font-semibold text-white transition duration-200"
              >
                Create a Learning Goal
              </button>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
