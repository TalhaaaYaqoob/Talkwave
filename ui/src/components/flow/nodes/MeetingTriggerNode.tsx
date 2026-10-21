"use client";

import { Ear, MessageSquare, Plus, Trash2, Users, Zap } from "lucide-react";
import { memo, useCallback, useEffect, useRef, useState } from "react";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import type { MeetingTriggerNodeData, MeetingTriggerMode } from "../types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { NodeContent } from "./common/NodeContent";
import { NodeEditDialog } from "./common/NodeEditDialog";
import { useNodeHandlers } from "./common/useNodeHandlers";

interface MeetingTriggerNodeProps {
  data: MeetingTriggerNodeData;
  selected?: boolean;
  id: string;
}

const TRIGGER_MODES: { value: MeetingTriggerMode; label: string; icon: typeof Ear; description: string }[] = [
  { value: "wake_word", label: "Wake Word", icon: Ear, description: "Responds when a wake word is spoken" },
  { value: "always_listen", label: "Always Listen", icon: MessageSquare, description: "Listens and responds to all direct questions" },
  { value: "speaker_filter", label: "Speaker Filter", icon: Users, description: "Only responds to specific speakers" },
  { value: "topic_detect", label: "Topic Detect", icon: Zap, description: "Activates when certain topics are mentioned" },
];

const TRIGGER_MODE_COLORS: Record<string, string> = {
  wake_word: "text-violet-400",
  speaker_filter: "text-primary",
  topic_detect: "text-amber-400",
  always_listen: "text-green-400",
};

export const MeetingTriggerNode = memo(({ data, selected, id }: MeetingTriggerNodeProps) => {
  const { open, setOpen, handleSaveNodeData, handleClearValidation, handleRestoreValidation } = useNodeHandlers({ id });
  const { saveWorkflow } = useWorkflow();

  const [name, setName] = useState(data.name || "Wake Word Trigger");
  const [mode, setMode] = useState<MeetingTriggerMode>(data.trigger_config?.mode || "wake_word");
  const [wakeWords, setWakeWords] = useState<string[]>(data.trigger_config?.wake_words || ["hey agent"]);
  const [speakerFilter, setSpeakerFilter] = useState<string[]>(data.trigger_config?.speaker_filter || []);
  const [topicKeywords, setTopicKeywords] = useState<string[]>(data.trigger_config?.topic_keywords || []);
  const [cooldown, setCooldown] = useState(data.trigger_config?.cooldown_seconds || 2);
  const [responsePrompt, setResponsePrompt] = useState(data.response_prompt || "");
  const [newWakeWord, setNewWakeWord] = useState("");
  const [newSpeaker, setNewSpeaker] = useState("");
  const [newTopic, setNewTopic] = useState("");

  useEffect(() => {
    setName(data.name || "Wake Word Trigger");
    setMode(data.trigger_config?.mode || "wake_word");
    setWakeWords(data.trigger_config?.wake_words || ["hey agent"]);
    setSpeakerFilter(data.trigger_config?.speaker_filter || []);
    setTopicKeywords(data.trigger_config?.topic_keywords || []);
    setCooldown(data.trigger_config?.cooldown_seconds || 2);
    setResponsePrompt(data.response_prompt || "");
  }, [open, data]);

  const hasChanges = name !== (data.name || "Wake Word Trigger") ||
    mode !== (data.trigger_config?.mode || "wake_word") ||
    JSON.stringify(wakeWords) !== JSON.stringify(data.trigger_config?.wake_words || ["hey agent"]) ||
    JSON.stringify(speakerFilter) !== JSON.stringify(data.trigger_config?.speaker_filter || []) ||
    JSON.stringify(topicKeywords) !== JSON.stringify(data.trigger_config?.topic_keywords || []) ||
    cooldown !== (data.trigger_config?.cooldown_seconds || 2) ||
    responsePrompt !== (data.response_prompt || "");

  const handleSave = useCallback(() => {
    handleSaveNodeData({
      name,
      trigger_config: {
        mode,
        wake_words: wakeWords,
        speaker_filter: speakerFilter,
        topic_keywords: topicKeywords,
        cooldown_seconds: cooldown,
      },
      response_prompt: responsePrompt,
    } as unknown as import("../types").FlowNodeData);
    setOpen(false);
    saveWorkflow?.();
  }, [name, mode, wakeWords, speakerFilter, topicKeywords, cooldown, responsePrompt, handleSaveNodeData, setOpen, saveWorkflow]);

  const addToList = (list: string[], setList: (v: string[]) => void, value: string, setInput: (v: string) => void) => {
    const trimmed = value.trim();
    if (trimmed && !list.includes(trimmed)) {
      setList([...list, trimmed]);
      setInput("");
    }
  };

  const removeFromList = (list: string[], setList: (v: string[]) => void, index: number) => {
    setList(list.filter((_, i) => i !== index));
  };

  const modeInfo = TRIGGER_MODES.find(m => m.value === mode) || TRIGGER_MODES[0];
  const ModeIcon = modeInfo.icon;

  const displayPrompt = data.response_prompt
    ? data.response_prompt.length > 80
      ? data.response_prompt.slice(0, 80) + "..."
      : data.response_prompt
    : "No response prompt set";

  return (
    <>
      <NodeContent
        selected={!!selected}
        invalid={data.invalid}
        selected_through_edge={data.selected_through_edge}
        hovered_through_edge={data.hovered_through_edge}
        title={data.name || "Wake Word Trigger"}
        icon={<ModeIcon className={cn("h-4 w-4", TRIGGER_MODE_COLORS[data.trigger_config?.mode || "wake_word"])} />}
        nodeType="meetingTrigger"
        hasTargetHandle={false}
        hasSourceHandle={true}
        onDoubleClick={() => setOpen(true)}
        onEdit={() => setOpen(true)}
        nodeId={id}
      >
        {/* Wake words display */}
        {data.trigger_config?.mode === "wake_word" && data.trigger_config?.wake_words && (
          <div className="flex flex-wrap gap-1 mb-2">
            {data.trigger_config.wake_words.map((word, i) => (
              <span key={i} className="px-2 py-0.5 text-[11px] bg-violet-500/10 text-violet-300 rounded-full border border-violet-500/20">
                &quot;{word}&quot;
              </span>
            ))}
          </div>
        )}
        <p className="text-sm text-muted-foreground/90 leading-relaxed font-light">{displayPrompt}</p>
      </NodeContent>

      <NodeEditDialog
        open={open}
        onOpenChange={setOpen}
        nodeData={data as unknown as import("../types").FlowNodeData}
        title="Edit Meeting Trigger"
        onSave={handleSave}
        hasChanges={hasChanges}
      >
        <div className="space-y-6">
          {/* Name */}
          <div className="space-y-2">
            <Label>Node Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Wake Word Trigger" />
          </div>

          {/* Trigger Mode */}
          <div className="space-y-3">
            <Label>Trigger Mode</Label>
            <div className="grid grid-cols-2 gap-2">
              {TRIGGER_MODES.map((m) => {
                const Icon = m.icon;
                return (
                  <button
                    key={m.value}
                    onClick={() => setMode(m.value)}
                    className={cn(
                      "flex items-start gap-2.5 p-3 rounded-lg border text-left transition-all",
                      mode === m.value
                        ? "border-primary bg-primary/10"
                        : "border-white/10 bg-white/[0.02] hover:border-white/20"
                    )}
                  >
                    <Icon className={cn("h-4 w-4 mt-0.5 flex-shrink-0", TRIGGER_MODE_COLORS[m.value])} />
                    <div>
                      <p className="text-sm font-medium">{m.label}</p>
                      <p className="text-[11px] text-muted-foreground mt-0.5">{m.description}</p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Mode-specific settings */}
          {mode === "wake_word" && (
            <div className="space-y-3">
              <Label>Wake Words</Label>
              <div className="flex flex-wrap gap-1.5 mb-2">
                {wakeWords.map((word, i) => (
                  <span key={i} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-violet-500/10 text-violet-300 rounded-full border border-violet-500/20">
                    &quot;{word}&quot;
                    <button onClick={() => removeFromList(wakeWords, setWakeWords, i)} className="hover:text-red-400 transition-colors">
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
              <div className="flex gap-2">
                <Input
                  value={newWakeWord}
                  onChange={(e) => setNewWakeWord(e.target.value)}
                  placeholder="Add wake word..."
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addToList(wakeWords, setWakeWords, newWakeWord, setNewWakeWord))}
                />
                <Button variant="outline" size="sm" onClick={() => addToList(wakeWords, setWakeWords, newWakeWord, setNewWakeWord)}>
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          )}

          {mode === "speaker_filter" && (
            <div className="space-y-3">
              <Label>Speakers to Respond To</Label>
              <div className="flex flex-wrap gap-1.5 mb-2">
                {speakerFilter.map((speaker, i) => (
                  <span key={i} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-primary/10 text-[#9af8df] rounded-full border border-primary/20">
                    {speaker}
                    <button onClick={() => removeFromList(speakerFilter, setSpeakerFilter, i)} className="hover:text-red-400 transition-colors">
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
              <div className="flex gap-2">
                <Input
                  value={newSpeaker}
                  onChange={(e) => setNewSpeaker(e.target.value)}
                  placeholder="Add speaker name..."
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addToList(speakerFilter, setSpeakerFilter, newSpeaker, setNewSpeaker))}
                />
                <Button variant="outline" size="sm" onClick={() => addToList(speakerFilter, setSpeakerFilter, newSpeaker, setNewSpeaker)}>
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          )}

          {mode === "topic_detect" && (
            <div className="space-y-3">
              <Label>Topic Keywords</Label>
              <div className="flex flex-wrap gap-1.5 mb-2">
                {topicKeywords.map((topic, i) => (
                  <span key={i} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-amber-500/10 text-amber-300 rounded-full border border-amber-500/20">
                    {topic}
                    <button onClick={() => removeFromList(topicKeywords, setTopicKeywords, i)} className="hover:text-red-400 transition-colors">
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
              <div className="flex gap-2">
                <Input
                  value={newTopic}
                  onChange={(e) => setNewTopic(e.target.value)}
                  placeholder="Add topic keyword..."
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addToList(topicKeywords, setTopicKeywords, newTopic, setNewTopic))}
                />
                <Button variant="outline" size="sm" onClick={() => addToList(topicKeywords, setTopicKeywords, newTopic, setNewTopic)}>
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          )}

          {/* Cooldown */}
          <div className="space-y-2">
            <Label>Cooldown Between Responses (seconds)</Label>
            <Input
              type="number"
              value={cooldown}
              onChange={(e) => setCooldown(Math.max(0, parseFloat(e.target.value) || 0))}
              min={0}
              max={10}
              step={0.5}
            />
          </div>

          {/* Response Prompt */}
          <div className="space-y-2">
            <Label>Response Prompt</Label>
            <p className="text-xs text-muted-foreground">How the agent should respond when triggered</p>
            <Textarea
              value={responsePrompt}
              onChange={(e) => setResponsePrompt(e.target.value)}
              placeholder="Respond helpfully and concisely..."
              rows={4}
              className="resize-none"
            />
          </div>
        </div>
      </NodeEditDialog>
    </>
  );
});

MeetingTriggerNode.displayName = "MeetingTriggerNode";

export default MeetingTriggerNode;
