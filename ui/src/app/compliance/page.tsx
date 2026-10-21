"use client";

import {
    ShieldCheck,
    Prohibit,
    SealCheck,
    ClipboardText,
    Trash,
    Plus,
    MagnifyingGlass,
} from "@phosphor-icons/react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getBackendUrl } from "@/lib/apiClient";
import { useAuth } from "@/lib/auth";

interface DNCEntry {
    id: number;
    phone_number: string;
    source: string;
    country_code?: string | null;
    notes?: string | null;
    added_at?: string | null;
}

interface ConsentRecord {
    id: number;
    phone_number: string;
    consent_type: string;
    regulation: string;
    consent_source?: string | null;
    is_active: boolean;
    consent_given_at?: string | null;
}

interface AuditEntry {
    id: number;
    action: string;
    regulation?: string | null;
    campaign_id?: number | null;
    phone_number_hash?: string | null;
    details: Record<string, unknown>;
    created_at?: string | null;
}

const ACTION_LABELS: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
    call_allowed: { label: "Call Allowed", variant: "default" },
    call_blocked_dnc: { label: "Blocked: DNC", variant: "destructive" },
    call_blocked_no_consent: { label: "Blocked: No Consent", variant: "destructive" },
    call_blocked_hours: { label: "Blocked: Hours", variant: "destructive" },
    consent_recorded: { label: "Consent Recorded", variant: "secondary" },
    consent_revoked: { label: "Consent Revoked", variant: "outline" },
    dnc_added: { label: "DNC Added", variant: "secondary" },
    dnc_removed: { label: "DNC Removed", variant: "outline" },
    ai_disclosure_played: { label: "AI Disclosure", variant: "secondary" },
    data_erased: { label: "Data Erased", variant: "outline" },
};

export default function CompliancePage() {
    const { user, getAccessToken, redirectToLogin, loading } = useAuth();

    const [dncEntries, setDncEntries] = useState<DNCEntry[]>([]);
    const [dncTotal, setDncTotal] = useState(0);
    const [consentRecords, setConsentRecords] = useState<ConsentRecord[]>([]);
    const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([]);
    const [isLoading, setIsLoading] = useState(true);

    const [newDncNumbers, setNewDncNumbers] = useState("");
    const [newConsentPhone, setNewConsentPhone] = useState("");
    const [consentSearch, setConsentSearch] = useState("");

    useEffect(() => {
        if (!loading && !user) redirectToLogin();
    }, [loading, user, redirectToLogin]);

    const apiFetch = useCallback(
        async (path: string, options: RequestInit = {}) => {
            const token = await getAccessToken();
            const res = await fetch(`${getBackendUrl()}/api/v1/compliance${path}`, {
                ...options,
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`,
                    ...(options.headers || {}),
                },
            });
            if (!res.ok) {
                const body = await res.json().catch(() => ({}));
                throw new Error(body?.detail || `Request failed (${res.status})`);
            }
            return res.json();
        },
        [getAccessToken],
    );

    const loadDnc = useCallback(async () => {
        try {
            const data = await apiFetch("/dnc?limit=100");
            setDncEntries(data.entries || []);
            setDncTotal(data.total || 0);
        } catch (e) {
            console.error(e);
        }
    }, [apiFetch]);

    const loadConsent = useCallback(
        async (search?: string) => {
            try {
                const q = search ? `&phone_number=${encodeURIComponent(search)}` : "";
                const data = await apiFetch(`/consent?limit=100${q}`);
                setConsentRecords(data.records || []);
            } catch (e) {
                console.error(e);
            }
        },
        [apiFetch],
    );

    const loadAudit = useCallback(async () => {
        try {
            const data = await apiFetch("/audit-log?limit=100");
            setAuditEntries(data.entries || []);
        } catch (e) {
            console.error(e);
        }
    }, [apiFetch]);

    useEffect(() => {
        if (!user) return;
        setIsLoading(true);
        Promise.all([loadDnc(), loadConsent(), loadAudit()]).finally(() =>
            setIsLoading(false),
        );
    }, [user, loadDnc, loadConsent, loadAudit]);

    const handleAddDnc = async () => {
        const numbers = newDncNumbers
            .split(/[\n,]/)
            .map((s) => s.trim())
            .filter(Boolean);
        if (numbers.length === 0) {
            toast.error("Enter at least one phone number");
            return;
        }
        try {
            const result = await apiFetch("/dnc", {
                method: "POST",
                body: JSON.stringify({ phone_numbers: numbers }),
            });
            toast.success(`Added ${result.added} number(s) to suppression list`);
            setNewDncNumbers("");
            loadDnc();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Failed to add numbers");
        }
    };

    const handleRemoveDnc = async (phone: string) => {
        try {
            await apiFetch(`/dnc/${encodeURIComponent(phone)}`, { method: "DELETE" });
            toast.success("Removed from suppression list");
            loadDnc();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Failed to remove");
        }
    };

    const handleAddConsent = async () => {
        if (!newConsentPhone.trim()) {
            toast.error("Enter a phone number");
            return;
        }
        try {
            await apiFetch("/consent", {
                method: "POST",
                body: JSON.stringify({
                    phone_number: newConsentPhone.trim(),
                    consent_type: "express_written",
                }),
            });
            toast.success("Consent recorded");
            setNewConsentPhone("");
            loadConsent();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Failed to record consent");
        }
    };

    const handleRevokeConsent = async (phone: string) => {
        try {
            await apiFetch(`/consent/${encodeURIComponent(phone)}`, {
                method: "DELETE",
            });
            toast.success("Consent revoked and number suppressed");
            loadConsent();
            loadDnc();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Failed to revoke");
        }
    };

    const fmtDate = (d?: string | null) =>
        d ? new Date(d).toLocaleString() : "—";

    return (
        <div className="container mx-auto px-4 py-8 max-w-6xl">
            <div className="flex items-center gap-3 mb-2">
                <div className="w-10 h-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
                    <ShieldCheck weight="duotone" className="w-5 h-5" />
                </div>
                <div>
                    <h1 className="text-2xl font-bold tracking-tight">Compliance</h1>
                    <p className="text-sm text-muted-foreground">
                        Manage your Do-Not-Call list, consent records, and compliance
                        audit trail (TCPA, DNC, PECR, UK GDPR).
                    </p>
                </div>
            </div>

            <Tabs defaultValue="dnc" className="mt-6">
                <TabsList>
                    <TabsTrigger value="dnc" className="gap-1.5">
                        <Prohibit weight="duotone" className="w-4 h-4" /> Suppression List
                    </TabsTrigger>
                    <TabsTrigger value="consent" className="gap-1.5">
                        <SealCheck weight="duotone" className="w-4 h-4" /> Consent
                    </TabsTrigger>
                    <TabsTrigger value="audit" className="gap-1.5">
                        <ClipboardText weight="duotone" className="w-4 h-4" /> Audit Log
                    </TabsTrigger>
                </TabsList>

                {/* Suppression List */}
                <TabsContent value="dnc" className="mt-4">
                    <Card>
                        <CardHeader>
                            <CardTitle className="text-base">Add to Suppression List</CardTitle>
                            <CardDescription>
                                Numbers here are scrubbed before every outbound call. Enter
                                one per line or comma-separated.
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-3">
                            <textarea
                                className="w-full min-h-[90px] rounded-md border border-input bg-transparent px-3 py-2 text-sm"
                                placeholder="+14155550123&#10;+442071234567"
                                value={newDncNumbers}
                                onChange={(e) => setNewDncNumbers(e.target.value)}
                            />
                            <Button onClick={handleAddDnc} className="gap-1.5">
                                <Plus weight="bold" className="w-4 h-4" /> Add Numbers
                            </Button>
                        </CardContent>
                    </Card>

                    <Card className="mt-4">
                        <CardHeader>
                            <CardTitle className="text-base">
                                Suppressed Numbers{" "}
                                <span className="text-muted-foreground font-normal">
                                    ({dncTotal})
                                </span>
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Phone Number</TableHead>
                                        <TableHead>Source</TableHead>
                                        <TableHead>Country</TableHead>
                                        <TableHead>Added</TableHead>
                                        <TableHead className="w-10" />
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {dncEntries.length === 0 ? (
                                        <TableRow>
                                            <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                                                No suppressed numbers yet.
                                            </TableCell>
                                        </TableRow>
                                    ) : (
                                        dncEntries.map((e) => (
                                            <TableRow key={e.id}>
                                                <TableCell className="font-mono">{e.phone_number}</TableCell>
                                                <TableCell>
                                                    <Badge variant="outline">{e.source}</Badge>
                                                </TableCell>
                                                <TableCell>{e.country_code || "—"}</TableCell>
                                                <TableCell className="text-muted-foreground text-sm">
                                                    {fmtDate(e.added_at)}
                                                </TableCell>
                                                <TableCell>
                                                    <Button
                                                        variant="ghost"
                                                        size="icon"
                                                        onClick={() => handleRemoveDnc(e.phone_number)}
                                                    >
                                                        <Trash className="w-4 h-4 text-destructive" />
                                                    </Button>
                                                </TableCell>
                                            </TableRow>
                                        ))
                                    )}
                                </TableBody>
                            </Table>
                        </CardContent>
                    </Card>
                </TabsContent>

                {/* Consent */}
                <TabsContent value="consent" className="mt-4">
                    <Card>
                        <CardHeader>
                            <CardTitle className="text-base">Record Consent</CardTitle>
                            <CardDescription>
                                Log express written consent (TCPA) or opt-in (PECR) for a
                                number before calling.
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="flex gap-2 items-end flex-wrap">
                            <div className="flex-1 min-w-[220px]">
                                <Label className="text-xs mb-1.5 block">Phone Number</Label>
                                <Input
                                    placeholder="+14155550123"
                                    value={newConsentPhone}
                                    onChange={(e) => setNewConsentPhone(e.target.value)}
                                />
                            </div>
                            <Button onClick={handleAddConsent} className="gap-1.5">
                                <Plus weight="bold" className="w-4 h-4" /> Record
                            </Button>
                        </CardContent>
                    </Card>

                    <Card className="mt-4">
                        <CardHeader>
                            <CardTitle className="text-base">Consent Records</CardTitle>
                            <div className="flex gap-2 pt-2">
                                <Input
                                    placeholder="Search by phone number"
                                    value={consentSearch}
                                    onChange={(e) => setConsentSearch(e.target.value)}
                                    className="max-w-xs"
                                />
                                <Button
                                    variant="outline"
                                    onClick={() => loadConsent(consentSearch)}
                                    className="gap-1.5"
                                >
                                    <MagnifyingGlass className="w-4 h-4" /> Search
                                </Button>
                            </div>
                        </CardHeader>
                        <CardContent>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Phone Number</TableHead>
                                        <TableHead>Type</TableHead>
                                        <TableHead>Regulation</TableHead>
                                        <TableHead>Status</TableHead>
                                        <TableHead>Given</TableHead>
                                        <TableHead className="w-10" />
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {consentRecords.length === 0 ? (
                                        <TableRow>
                                            <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                                                No consent records yet.
                                            </TableCell>
                                        </TableRow>
                                    ) : (
                                        consentRecords.map((r) => (
                                            <TableRow key={r.id}>
                                                <TableCell className="font-mono">{r.phone_number}</TableCell>
                                                <TableCell>{r.consent_type.replace(/_/g, " ")}</TableCell>
                                                <TableCell>
                                                    <Badge variant="outline" className="uppercase">
                                                        {r.regulation}
                                                    </Badge>
                                                </TableCell>
                                                <TableCell>
                                                    <Badge variant={r.is_active ? "default" : "outline"}>
                                                        {r.is_active ? "Active" : "Revoked"}
                                                    </Badge>
                                                </TableCell>
                                                <TableCell className="text-muted-foreground text-sm">
                                                    {fmtDate(r.consent_given_at)}
                                                </TableCell>
                                                <TableCell>
                                                    {r.is_active && (
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            onClick={() => handleRevokeConsent(r.phone_number)}
                                                        >
                                                            <Trash className="w-4 h-4 text-destructive" />
                                                        </Button>
                                                    )}
                                                </TableCell>
                                            </TableRow>
                                        ))
                                    )}
                                </TableBody>
                            </Table>
                        </CardContent>
                    </Card>
                </TabsContent>

                {/* Audit Log */}
                <TabsContent value="audit" className="mt-4">
                    <Card>
                        <CardHeader>
                            <CardTitle className="text-base">Compliance Audit Log</CardTitle>
                            <CardDescription>
                                Immutable record of every compliance decision. Retained for
                                5 years.
                            </CardDescription>
                        </CardHeader>
                        <CardContent>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Action</TableHead>
                                        <TableHead>Regulation</TableHead>
                                        <TableHead>Campaign</TableHead>
                                        <TableHead>When</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {auditEntries.length === 0 ? (
                                        <TableRow>
                                            <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                                                No audit entries yet.
                                            </TableCell>
                                        </TableRow>
                                    ) : (
                                        auditEntries.map((a) => {
                                            const meta = ACTION_LABELS[a.action] || {
                                                label: a.action,
                                                variant: "outline" as const,
                                            };
                                            return (
                                                <TableRow key={a.id}>
                                                    <TableCell>
                                                        <Badge variant={meta.variant}>{meta.label}</Badge>
                                                    </TableCell>
                                                    <TableCell className="uppercase text-xs text-muted-foreground">
                                                        {a.regulation || "—"}
                                                    </TableCell>
                                                    <TableCell>{a.campaign_id ?? "—"}</TableCell>
                                                    <TableCell className="text-muted-foreground text-sm">
                                                        {fmtDate(a.created_at)}
                                                    </TableCell>
                                                </TableRow>
                                            );
                                        })
                                    )}
                                </TableBody>
                            </Table>
                        </CardContent>
                    </Card>
                </TabsContent>
            </Tabs>

            {isLoading && (
                <p className="text-center text-muted-foreground text-sm mt-6">
                    Loading compliance data…
                </p>
            )}
        </div>
    );
}
