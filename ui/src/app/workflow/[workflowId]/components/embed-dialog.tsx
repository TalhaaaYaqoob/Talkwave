"use client";

import { Check, Copy, Plus, Trash2 } from "lucide-react";

import { Spinner } from "@/components/ui/ai-loader";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getBackendUrl } from "@/lib/apiClient";

interface EmbedToken {
    id: number;
    token: string;
    workflow_id: number;
    allowed_domains: string[] | null;
    is_active: boolean;
    usage_count: number;
    usage_limit: number | null;
    created_at: string;
    expires_at: string | null;
    embed_snippet: string;
}

interface EmbedDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    workflowId: number;
    getAccessToken: () => Promise<string>;
}

export function EmbedDialog({ open, onOpenChange, workflowId, getAccessToken }: EmbedDialogProps) {
    const [tokens, setTokens] = useState<EmbedToken[]>([]);
    const [loading, setLoading] = useState(false);
    const [creating, setCreating] = useState(false);
    const [copiedId, setCopiedId] = useState<number | null>(null);
    const [allowedDomains, setAllowedDomains] = useState("");

    const apiUrl = getBackendUrl();

    const fetchTokens = useCallback(async () => {
        setLoading(true);
        try {
            const accessToken = await getAccessToken();
            const res = await fetch(`${apiUrl}/api/v1/embed/tokens/${workflowId}`, {
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (res.ok) {
                setTokens(await res.json());
            }
        } catch (e) {
            console.error("Failed to fetch embed tokens", e);
        } finally {
            setLoading(false);
        }
    }, [apiUrl, workflowId, getAccessToken]);

    useEffect(() => {
        if (open) fetchTokens();
    }, [open, fetchTokens]);

    const createToken = async () => {
        setCreating(true);
        try {
            const accessToken = await getAccessToken();
            const body: Record<string, unknown> = { workflow_id: workflowId };
            if (allowedDomains.trim()) {
                body.allowed_domains = allowedDomains.split(",").map((d) => d.trim()).filter(Boolean);
            }
            const res = await fetch(`${apiUrl}/api/v1/embed/tokens`, {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${accessToken}`,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(body),
            });
            if (res.ok) {
                setAllowedDomains("");
                await fetchTokens();
            }
        } catch (e) {
            console.error("Failed to create embed token", e);
        } finally {
            setCreating(false);
        }
    };

    const deactivateToken = async (tokenId: number) => {
        try {
            const accessToken = await getAccessToken();
            await fetch(`${apiUrl}/api/v1/embed/tokens/${tokenId}`, {
                method: "DELETE",
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            await fetchTokens();
        } catch (e) {
            console.error("Failed to deactivate token", e);
        }
    };

    const copyToClipboard = async (text: string, id: number) => {
        await navigator.clipboard.writeText(text);
        setCopiedId(id);
        setTimeout(() => setCopiedId(null), 2000);
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl bg-[#0A0A0A] border-white/10">
                <DialogHeader>
                    <DialogTitle>Embed Voice Agent on Your Website</DialogTitle>
                    <DialogDescription>
                        Generate an embed token and paste the snippet into your website&apos;s HTML.
                        Visitors can then talk to your voice agent directly.
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-6 py-2">
                    <div className="space-y-3 rounded-lg border border-white/10 p-4">
                        <Label className="text-sm font-medium">Create New Embed Token</Label>
                        <div className="flex gap-2">
                            <Input
                                placeholder="Allowed domains (comma-separated, e.g. example.com, app.example.com)"
                                value={allowedDomains}
                                onChange={(e) => setAllowedDomains(e.target.value)}
                                className="flex-1 bg-[#111] border-white/10"
                            />
                            <Button onClick={createToken} disabled={creating} size="sm">
                                {creating ? (
                                    <Spinner size="sm" />
                                ) : (
                                    <Plus className="h-4 w-4 mr-1" />
                                )}
                                Generate
                            </Button>
                        </div>
                        <p className="text-xs text-muted-foreground">
                            Leave domains empty to allow any website. For security, specify your domains.
                        </p>
                    </div>

                    <div className="space-y-3">
                        <Label className="text-sm font-medium">
                            Active Tokens {!loading && `(${tokens.filter((t) => t.is_active).length})`}
                        </Label>

                        {loading ? (
                            <div className="flex justify-center py-6">
                                <Spinner size="md" />
                            </div>
                        ) : tokens.filter((t) => t.is_active).length === 0 ? (
                            <p className="text-sm text-muted-foreground py-4 text-center">
                                No embed tokens yet. Create one above to get started.
                            </p>
                        ) : (
                            <div className="space-y-3 max-h-80 overflow-y-auto">
                                {tokens
                                    .filter((t) => t.is_active)
                                    .map((token) => (
                                        <div
                                            key={token.id}
                                            className="rounded-lg border border-white/10 p-4 space-y-3"
                                        >
                                            <div className="flex items-center justify-between">
                                                <div className="text-xs text-muted-foreground">
                                                    Created {new Date(token.created_at).toLocaleDateString()}
                                                    {" \u00b7 "}
                                                    {token.usage_count} uses
                                                    {token.allowed_domains?.length
                                                        ? ` \u00b7 ${token.allowed_domains.join(", ")}`
                                                        : " \u00b7 Any domain"}
                                                </div>
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => deactivateToken(token.id)}
                                                    className="h-7 w-7 text-destructive hover:text-destructive hover:bg-destructive/10"
                                                >
                                                    <Trash2 className="h-3.5 w-3.5" />
                                                </Button>
                                            </div>

                                            <div className="relative min-w-0">
                                                <pre className="text-xs bg-[#111] rounded-md p-3 pr-10 border border-white/5 whitespace-pre-wrap break-all overflow-hidden">
                                                    <code>{token.embed_snippet}</code>
                                                </pre>
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() =>
                                                        copyToClipboard(token.embed_snippet, token.id)
                                                    }
                                                    className="absolute top-2 right-2 h-7 w-7"
                                                >
                                                    {copiedId === token.id ? (
                                                        <Check className="h-3.5 w-3.5 text-green-400" />
                                                    ) : (
                                                        <Copy className="h-3.5 w-3.5" />
                                                    )}
                                                </Button>
                                            </div>
                                        </div>
                                    ))}
                            </div>
                        )}
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
