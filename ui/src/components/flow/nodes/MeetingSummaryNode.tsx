"use client";

import { CheckSquare, Clock, FileText, ListChecks } from "lucide-react";
import { memo, useCallback, useEffect, useState } from "react";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import type { MeetingSummaryNodeData, MeetingSummaryMode } from "../types";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import { NodeContent } from "./common/NodeContent";
import { NodeEditDialog } from "./common/NodeEditDialog";
import { useNodeHandlers } from "./common/useNodeHandlers";

interface MeetingSummaryNodeProps {
  data: MeetingSummaryNodeData;
  selected?: boolean;
  id: string;
}

const SUMMARY_MODES: { value: MeetingSummaryMode; label: string; icon: typeof Clock; description: string }[] = [
  { value: "end_of_meeting", label: "End of Meeting", icon: ListChecks, description: "Generate summary when the meeting ends" },
  { value: "periodic", label: "Periodic", icon: Clock, description: "Generate summaries at regular intervals" },
  { value: "on_demand", label: "On Demand", icon: FileText, description: "Generate summary when requested" },
];

const OUTPUT_FORMATS: { value: string; label: string }[] = [
  { value: "markdown", label: "Markdown" },
  { value: "text", label: "Plain Text" },
  { value: "json", label: "JSON" },
];

export const MeetingSummaryNode = memo(({ data, selected, id }: MeetingSummaryNodeProps) => {
  const { open, setOpen, handleSaveNodeData } = useNodeHandlers({ id });
  const { saveWorkflow } = useWorkflow();

  const [name, setName] = useState(data.name || "Meeting Summary");
  const [mode, setMode] = useState<MeetingSummaryMode>(data.summary_config?.mode || "end_of_meeting");
  const [intervalMinutes, setIntervalMinutes] = useState(data.summary_config?.interval_minutes || 15);
  const [includeActionItems, setIncludeActionItems] = useState(data.summary_config?.include_action_items ?? true);
  const [includeDecisions, setIncludeDecisions] = useState(data.summary_config?.include_decisions ?? true);
  const [includeKeyPoints, setIncludeKeyPoints] = useState(data.summary_config?.include_key_points ?? true);
  const [outputFormat, setOutputFormat] = useState(data.output_format || "markdown");

  useEffect(() => {
    setName(data.name || "Meeting Summary");
    setMode(data.summary_config?.mode || "end_of_meeting");
    setIntervalMinutes(data.summary_config?.interval_minutes || 15);
    setIncludeActionItems(data.summary_config?.include_action_items ?? true);
    setIncludeDecisions(data.summary_config?.include_decisions ?? true);
    setIncludeKeyPoints(data.summary_config?.include_key_points ?? true);
    setOutputFormat(data.output_format || "markdown");
  }, [open, data]);

  const hasChanges = name !== (data.name || "Meeting Summary") ||
    mode !== (data.summary_config?.mode || "end_of_meeting") ||
    intervalMinutes !== (data.summary_config?.interval_minutes || 15) ||
    includeActionItems !== (data.summary_config?.include_action_items ?? true) ||
    includeDecisions !== (data.summary_config?.include_decisions ?? true) ||
    includeKeyPoints !== (data.summary_config?.include_key_points ?? true) ||
    outputFormat !== (data.output_format || "markdown");

  const handleSave = useCallback(() => {
    handleSaveNodeData({
      name,
      summary_config: {
        mode,
        interval_minutes: intervalMinutes,
        include_action_items: includeActionItems,
        include_decisions: includeDecisions,
        include_key_points: includeKeyPoints,
      },
      output_format: outputFormat,
    } as unknown as import("../types").FlowNodeData);
    setOpen(false);
    saveWorkflow?.();
  }, [name, mode, intervalMinutes, includeActionItems, includeDecisions, includeKeyPoints, outputFormat, handleSaveNodeData, setOpen, saveWorkflow]);

  const features = [];
  if (data.summary_config?.include_key_points) features.push("Key Points");
  if (data.summary_config?.include_action_items) features.push("Action Items");
  if (data.summary_config?.include_decisions) features.push("Decisions");

  const modeInfo = SUMMARY_MODES.find(m => m.value === (data.summary_config?.mode || "end_of_meeting")) || SUMMARY_MODES[0];
  const ModeIcon = modeInfo.icon;

  return (
    <>
      <NodeContent
        selected={!!selected}
        invalid={data.invalid}
        selected_through_edge={data.selected_through_edge}
        hovered_through_edge={data.hovered_through_edge}
        title={data.name || "Meeting Summary"}
        icon={<ModeIcon className="h-4 w-4 text-teal-400" />}
        nodeType="meetingSummary"
        hasTargetHandle={true}
        hasSourceHandle={false}
        onDoubleClick={() => setOpen(true)}
        onEdit={() => setOpen(true)}
        nodeId={id}
      >
        <div className="space-y-2">
          {features.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {features.map((f) => (
                <span
                  key={f}
                  className="flex items-center gap-1 px-2 py-0.5 text-[11px] bg-teal-500/10 text-teal-300 rounded-full border border-teal-500/20"
                >
                  <CheckSquare className="h-2.5 w-2.5" />
                  {f}
                </span>
              ))}
            </div>
          )}
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <FileText className="h-3 w-3" />
            Output: {data.output_format || "markdown"}
          </div>
        </div>
      </NodeContent>

      <NodeEditDialog
        open={open}
        onOpenChange={setOpen}
        nodeData={data as unknown as import("../types").FlowNodeData}
        title="Edit Meeting Summary"
        onSave={handleSave}
        hasChanges={hasChanges}
      >
        <div className="space-y-6">
          {/* Name */}
          <div className="space-y-2">
            <Label>Node Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Meeting Summary" />
          </div>

          {/* Summary Mode */}
          <div className="space-y-3">
            <Label>Summary Mode</Label>
            <div className="grid grid-cols-1 gap-2">
              {SUMMARY_MODES.map((m) => {
                const Icon = m.icon;
                return (
                  <button
                    key={m.value}
                    onClick={() => setMode(m.value)}
                    className={cn(
                      "flex items-start gap-3 p-3 rounded-lg border text-left transition-all",
                      mode === m.value
                        ? "border-teal-500 bg-teal-500/10"
                        : "border-white/10 bg-white/[0.02] hover:border-white/20"
                    )}
                  >
                    <Icon className={cn("h-4 w-4 mt-0.5 flex-shrink-0", mode === m.value ? "text-teal-400" : "text-muted-foreground")} />
                    <div>
                      <p className="text-sm font-medium">{m.label}</p>
                      <p className="text-[11px] text-muted-foreground mt-0.5">{m.description}</p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Periodic interval */}
          {mode === "periodic" && (
            <div className="space-y-2">
              <Label>Interval (minutes)</Label>
              <Input
                type="number"
                value={intervalMinutes}
                onChange={(e) => setIntervalMinutes(Math.max(1, parseInt(e.target.value) || 15))}
                min={1}
                max={120}
              />
            </div>
          )}

          {/* Include toggles */}
          <div className="space-y-4">
            <Label>Summary Content</Label>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Key Points</p>
                  <p className="text-xs text-muted-foreground">Main discussion points and topics covered</p>
                </div>
                <Switch checked={includeKeyPoints} onCheckedChange={setIncludeKeyPoints} />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Action Items</p>
                  <p className="text-xs text-muted-foreground">Tasks and follow-ups assigned during the meeting</p>
                </div>
                <Switch checked={includeActionItems} onCheckedChange={setIncludeActionItems} />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Decisions</p>
                  <p className="text-xs text-muted-foreground">Key decisions made during the meeting</p>
                </div>
                <Switch checked={includeDecisions} onCheckedChange={setIncludeDecisions} />
              </div>
            </div>
          </div>

          {/* Output Format */}
          <div className="space-y-3">
            <Label>Output Format</Label>
            <div className="flex gap-2">
              {OUTPUT_FORMATS.map((f) => (
                <button
                  key={f.value}
                  onClick={() => setOutputFormat(f.value)}
                  className={cn(
                    "px-3 py-1.5 rounded-lg border text-sm transition-all",
                    outputFormat === f.value
                      ? "border-teal-500 bg-teal-500/10 text-teal-400"
                      : "border-white/10 bg-white/[0.02] text-muted-foreground hover:border-white/20"
                  )}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </NodeEditDialog>
    </>
  );
});

MeetingSummaryNode.displayName = "MeetingSummaryNode";

export default MeetingSummaryNode;
