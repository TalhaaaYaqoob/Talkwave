"use client";

import { Clock, Sparkles, Users, Video, Mic, FileText } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export default function MeetingAgentPage() {
  return (
    <div className="flex items-center justify-center min-h-[80vh] p-4 sm:p-6">
      <div className="text-center max-w-lg space-y-8">
        <div className="relative mx-auto w-20 h-20">
          <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-primary/20 to-teal-500/20 blur-xl" />
          <div className="relative flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-primary/10 to-teal-500/10 border border-primary/15">
            <Users className="h-9 w-9 text-primary" />
          </div>
        </div>

        <div className="space-y-3">
          <Badge variant="outline" className="border-primary/40 text-primary text-xs px-3 py-1">
            <Clock className="h-3 w-3 mr-1.5" />
            Coming Soon
          </Badge>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">Meeting Agent</h1>
          <p className="text-muted-foreground leading-relaxed">
            An AI assistant that joins your meetings, listens for questions,
            takes notes, and provides real-time answers — so you can focus on the conversation.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 sm:gap-3 max-w-sm mx-auto w-full px-4 sm:px-0">
          {[
            { icon: Video, label: "Auto-join meetings" },
            { icon: Mic, label: "Wake-word activation" },
            { icon: FileText, label: "Meeting summaries" },
            { icon: Sparkles, label: "AI-powered answers" },
          ].map(({ icon: Icon, label }) => (
            <div
              key={label}
              className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg border border-white/5 bg-white/[0.02] text-sm text-muted-foreground"
            >
              <Icon className="h-4 w-4 text-primary/70 shrink-0" />
              {label}
            </div>
          ))}
        </div>

        <p className="text-xs text-muted-foreground/60">
          We&apos;re working hard to bring this feature to you. Stay tuned!
        </p>
      </div>
    </div>
  );
}
