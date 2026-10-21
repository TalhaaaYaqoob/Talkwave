"use client";

import { Spinner } from "@/components/ui/ai-loader";
import {
  ArrowLeft,
  Bot,
  Clock,
  Copy,
  MessageSquare,
  Mic,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getBackendUrl } from "@/lib/apiClient";
import { useAuth } from "@/lib/auth";

interface TranscriptEntry {
  text: string;
  speaker: string;
  speaker_id?: string;
  speaker_name?: string;
  timestamp?: number;
  is_agent?: boolean;
}

interface SpeakerStat {
  display_name: string;
  utterance_count: number;
  total_words: number;
  talk_time_estimate_seconds: number;
}

interface SessionSummary {
  session_id: string;
  executive_summary: string;
  key_points: string[];
  action_items: { description: string; assignee?: string; priority?: string }[];
  decisions_made: string[];
  follow_ups: string[];
  duration_minutes: number;
  participant_count: number;
  speaker_stats: Record<string, SpeakerStat>;
  transcript: TranscriptEntry[];
}

interface SessionInfo {
  session_id: string;
  agent_name: string;
  status: string;
  meeting_url: string;
  created_at: number;
}

export default function MeetingSessionPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;
  const { user, getAccessToken, loading } = useAuth();

  const [session, setSession] = useState<SessionInfo | null>(null);
  const [summary, setSummary] = useState<SessionSummary | null>(null);
  const [loadingData, setLoadingData] = useState(true);
  const [summaryError, setSummaryError] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const token = await getAccessToken();
      const headers = { Authorization: `Bearer ${token}` };
      const base = getBackendUrl();

      const [sessionRes, summaryRes] = await Promise.all([
        fetch(`${base}/api/v1/meeting-agent/sessions/${sessionId}`, { headers }),
        fetch(`${base}/api/v1/meeting-agent/sessions/${sessionId}/summary`, { headers }),
      ]);

      if (sessionRes.ok) {
        setSession(await sessionRes.json());
      }

      if (summaryRes.ok) {
        setSummary(await summaryRes.json());
      } else if (summaryRes.status === 400) {
        setSummaryError("Summary is not ready yet. The meeting may still be processing.");
      } else {
        setSummaryError("Failed to load summary.");
      }
    } catch {
      setSummaryError("Failed to load meeting data.");
    } finally {
      setLoadingData(false);
    }
  }, [sessionId, getAccessToken]);

  useEffect(() => {
    if (!user) return;
    fetchData();
  }, [user, fetchData]);

  const transcript = summary?.transcript || [];
  const speakers = summary?.speaker_stats || {};
  const agentName = session?.agent_name || "TalkWave";

  const copyTranscript = () => {
    const text = transcript
      .map((e) => `[${e.speaker || e.speaker_name || "Unknown"}]: ${e.text}`)
      .join("\n");
    navigator.clipboard.writeText(text);
    toast.success("Transcript copied to clipboard");
  };

  if (loading || !user || loadingData) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/meeting-agent">
            <Button variant="ghost" size="icon">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <h1 className="text-xl font-bold flex items-center gap-2">
              <Bot className="h-5 w-5 text-primary" />
              {agentName}
              <Badge
                variant="outline"
                className="bg-gray-500/20 text-gray-400 border-gray-500/30"
              >
                Ended
              </Badge>
            </h1>
            <p className="text-sm text-muted-foreground flex items-center gap-2">
              <Clock className="h-3 w-3" />
              {(summary?.duration_minutes || 0).toFixed(0)} min
              {Object.keys(speakers).length > 0 && (
                <>
                  <span className="mx-1">&middot;</span>
                  <Users className="h-3 w-3" />
                  {Object.keys(speakers).length} participants
                </>
              )}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          {transcript.length > 0 && (
            <Button variant="outline" size="sm" onClick={copyTranscript}>
              <Copy className="h-3 w-3 mr-1" />
              Copy Transcript
            </Button>
          )}
        </div>
      </div>

      <Separator />

      {summaryError && !summary ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <MessageSquare className="h-8 w-8 mb-3" />
            <p className="text-sm">{summaryError}</p>
            <Button variant="outline" size="sm" className="mt-4" onClick={() => { setLoadingData(true); setSummaryError(""); fetchData(); }}>
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          <div className="lg:col-span-3">
            <Tabs defaultValue={summary?.executive_summary ? "summary" : "transcript"}>
              <TabsList>
                <TabsTrigger value="transcript" className="flex items-center gap-1">
                  <Mic className="h-3 w-3" />
                  Transcript
                </TabsTrigger>
                {summary?.executive_summary && (
                  <TabsTrigger value="summary" className="flex items-center gap-1">
                    <MessageSquare className="h-3 w-3" />
                    Summary
                  </TabsTrigger>
                )}
              </TabsList>

              <TabsContent value="transcript">
                <Card className="h-[65vh]">
                  <ScrollArea className="h-full p-4">
                    {transcript.length === 0 ? (
                      <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                        <Mic className="h-8 w-8 mb-2" />
                        <p>No transcript available for this meeting.</p>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {transcript.map((entry, i) => {
                          const name = entry.speaker || entry.speaker_name || "Unknown";
                          const isAgent = entry.is_agent || name.toLowerCase() === agentName.toLowerCase();
                          return (
                            <div
                              key={i}
                              className={`flex gap-3 ${isAgent ? "bg-primary/5 rounded-lg p-2 -mx-2" : ""}`}
                            >
                              <div
                                className={`h-7 w-7 rounded-full flex items-center justify-center text-xs font-medium shrink-0 mt-0.5 ${
                                  isAgent
                                    ? "bg-primary/20 text-primary"
                                    : "bg-muted text-muted-foreground"
                                }`}
                              >
                                {isAgent ? (
                                  <Bot className="h-3.5 w-3.5" />
                                ) : (
                                  name.charAt(0).toUpperCase()
                                )}
                              </div>
                              <div className="flex-1 min-w-0">
                                <span className={`text-sm font-medium ${isAgent ? "text-primary" : ""}`}>
                                  {isAgent ? agentName : name}
                                </span>
                                <p className="text-sm mt-0.5">{entry.text}</p>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </ScrollArea>
                </Card>
              </TabsContent>

              {summary?.executive_summary && (
                <TabsContent value="summary">
                  <Card className="h-[65vh]">
                    <ScrollArea className="h-full p-6">
                      <div className="space-y-6">
                        <div>
                          <h3 className="font-semibold mb-2">Overview</h3>
                          <p className="text-sm text-muted-foreground">
                            {summary.executive_summary}
                          </p>
                        </div>

                        {summary.key_points.length > 0 && (
                          <div>
                            <h3 className="font-semibold mb-2">Key Points</h3>
                            <ul className="list-disc list-inside space-y-1">
                              {summary.key_points.map((p, i) => (
                                <li key={i} className="text-sm text-muted-foreground">{p}</li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {summary.action_items.length > 0 && (
                          <div>
                            <h3 className="font-semibold mb-2">Action Items</h3>
                            <div className="space-y-2">
                              {summary.action_items.map((item, i) => (
                                <div key={i} className="flex items-start gap-2 text-sm">
                                  <Badge variant="outline" className="text-xs shrink-0 mt-0.5">
                                    {item.priority || "medium"}
                                  </Badge>
                                  <span className="text-muted-foreground">
                                    {item.description}
                                    {item.assignee && (
                                      <span className="font-medium text-foreground"> &rarr; {item.assignee}</span>
                                    )}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {summary.decisions_made.length > 0 && (
                          <div>
                            <h3 className="font-semibold mb-2">Decisions Made</h3>
                            <ul className="list-disc list-inside space-y-1">
                              {summary.decisions_made.map((d, i) => (
                                <li key={i} className="text-sm text-muted-foreground">{d}</li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {summary.follow_ups.length > 0 && (
                          <div>
                            <h3 className="font-semibold mb-2">Follow-ups</h3>
                            <ul className="list-disc list-inside space-y-1">
                              {summary.follow_ups.map((f, i) => (
                                <li key={i} className="text-sm text-muted-foreground">{f}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    </ScrollArea>
                  </Card>
                </TabsContent>
              )}
            </Tabs>
          </div>

          <div className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Participants</CardTitle>
                <CardDescription className="text-xs">
                  {Object.keys(speakers).length > 0
                    ? `${Object.keys(speakers).length} detected`
                    : "No data"}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {Object.entries(speakers).map(([id, stat]) => (
                  <div key={id} className="flex items-center gap-2">
                    <div className="h-6 w-6 rounded-full bg-muted flex items-center justify-center text-xs">
                      {stat.display_name.charAt(0).toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{stat.display_name}</p>
                      <p className="text-xs text-muted-foreground">
                        {stat.utterance_count} utterances &middot; {stat.total_words} words
                      </p>
                    </div>
                  </div>
                ))}
                {Object.keys(speakers).length === 0 && (
                  <p className="text-xs text-muted-foreground text-center py-4">
                    No speaker data available
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Meeting Stats</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Duration</span>
                  <span>{(summary?.duration_minutes || 0).toFixed(0)} min</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Transcript entries</span>
                  <span>{transcript.length}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Participants</span>
                  <span>{summary?.participant_count || Object.keys(speakers).length}</span>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
