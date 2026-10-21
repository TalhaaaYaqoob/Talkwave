'use client';

import { Book, Check, ChevronDown, ChevronRight, FileText, Info, Pencil, Plus, Trash2, Upload, X } from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useCallback, useEffect, useState } from 'react';

import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { DEFAULT_KNOWLEDGE_BASE_CONFIG, KnowledgeBaseConfig } from '@/components/flow/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { getBackendUrl } from '@/lib/apiClient';
import { useAuth } from '@/lib/auth';

interface KnowledgeBasePanelProps {
    config?: KnowledgeBaseConfig;
    setConfig: (config: KnowledgeBaseConfig) => void;
    workflowId?: number;
}

interface Document {
    id: number;
    name: string;
    description: string | null;
    file_type: string;
    file_size_bytes: number | null;
    chunk_count: number;
    is_active: boolean;
    processing_status: string;
    processing_error: string | null;
    created_at: string;
    updated_at: string;
}

export function KnowledgeBasePanel({ config: configProp, setConfig, workflowId }: KnowledgeBasePanelProps) {
    const config = configProp ?? DEFAULT_KNOWLEDGE_BASE_CONFIG;
    const { getAccessToken } = useAuth();

    const [documents, setDocuments] = useState<Document[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const [showAddForm, setShowAddForm] = useState(false);
    const [newDocName, setNewDocName] = useState('');
    const [newDocContent, setNewDocContent] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [deleteDocId, setDeleteDocId] = useState<number | null>(null);

    // Content editing state
    const [expandedDocId, setExpandedDocId] = useState<number | null>(null);
    const [editContent, setEditContent] = useState('');
    const [originalContent, setOriginalContent] = useState('');
    const [isLoadingContent, setIsLoadingContent] = useState(false);
    const [isSavingContent, setIsSavingContent] = useState(false);

    const fetchDocuments = useCallback(async () => {
        setIsLoading(true);
        setError(null);
        try {
            const accessToken = await getAccessToken();
            const params = new URLSearchParams();
            if (workflowId) params.set('workflow_id', String(workflowId));
            const qs = params.toString();
            const response = await fetch(`${getBackendUrl()}/api/v1/knowledge-base/documents${qs ? `?${qs}` : ''}`, {
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
            });
            if (response.ok) {
                const data = await response.json();
                setDocuments(data);
            } else {
                console.error('Failed to fetch documents:', response.status);
            }
        } catch (err) {
            console.error('Error fetching documents:', err);
        } finally {
            setIsLoading(false);
        }
    }, [getAccessToken, workflowId]);

    useEffect(() => {
        if (config.enabled) {
            fetchDocuments();
        }
    }, [config.enabled, fetchDocuments]);

    const handleToggle = (enabled: boolean) => {
        if (enabled) {
            setConfig({
                ...DEFAULT_KNOWLEDGE_BASE_CONFIG,
                ...config,
                enabled: true,
            });
        } else {
            setConfig({ ...config, enabled: false });
        }
    };

    const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        setIsUploading(true);
        setError(null);

        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('name', file.name);
            if (workflowId) formData.append('workflow_id', String(workflowId));

            const accessToken = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/knowledge-base/documents/upload`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
                body: formData,
            });

            if (response.ok) {
                await fetchDocuments();
            } else {
                const data = await response.json();
                setError(data.detail || 'Failed to upload file');
            }
        } catch (err) {
            setError('Error uploading file');
            console.error('Error uploading file:', err);
        } finally {
            setIsUploading(false);
            e.target.value = '';
        }
    };

    const handleAddDocument = async () => {
        if (!newDocName.trim() || !newDocContent.trim()) {
            setError('Name and content are required');
            return;
        }

        setIsUploading(true);
        setError(null);

        try {
            const accessToken = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/knowledge-base/documents`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${accessToken}`,
                },
                body: JSON.stringify({
                    name: newDocName,
                    content: newDocContent,
                    file_type: 'txt',
                    ...(workflowId ? { workflow_id: workflowId } : {}),
                }),
            });

            if (response.ok) {
                setNewDocName('');
                setNewDocContent('');
                setShowAddForm(false);
                await fetchDocuments();
            } else {
                const data = await response.json();
                setError(data.detail || 'Failed to create document');
            }
        } catch (err) {
            setError('Error creating document');
            console.error('Error creating document:', err);
        } finally {
            setIsUploading(false);
        }
    };

    const handleDeleteDocument = async (docId: number) => {
        try {
            const accessToken = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/knowledge-base/documents/${docId}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
            });

            if (response.ok) {
                if (expandedDocId === docId) {
                    setExpandedDocId(null);
                    setEditContent('');
                    setOriginalContent('');
                }
                await fetchDocuments();
            } else {
                setError('Failed to delete document');
            }
        } catch (err) {
            setError('Error deleting document');
            console.error('Error deleting document:', err);
        } finally {
            setDeleteDocId(null);
        }
    };

    // Fetch full content when expanding a document
    const handleToggleExpand = async (docId: number) => {
        if (expandedDocId === docId) {
            setExpandedDocId(null);
            setEditContent('');
            setOriginalContent('');
            return;
        }

        setExpandedDocId(docId);
        setIsLoadingContent(true);
        setError(null);

        try {
            const accessToken = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/knowledge-base/documents/${docId}/content`, {
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
            });

            if (response.ok) {
                const data = await response.json();
                setEditContent(data.content);
                setOriginalContent(data.content);
            } else {
                setError('Failed to load document content');
                setExpandedDocId(null);
            }
        } catch (err) {
            setError('Error loading document content');
            setExpandedDocId(null);
            console.error('Error loading content:', err);
        } finally {
            setIsLoadingContent(false);
        }
    };

    // Save edited content
    const handleSaveContent = async () => {
        if (expandedDocId === null || !editContent.trim()) return;

        setIsSavingContent(true);
        setError(null);

        try {
            const accessToken = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/knowledge-base/documents/${expandedDocId}/content`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${accessToken}`,
                },
                body: JSON.stringify({ content: editContent }),
            });

            if (response.ok) {
                setOriginalContent(editContent);
                await fetchDocuments();
            } else {
                const data = await response.json();
                setError(data.detail || 'Failed to save content');
            }
        } catch (err) {
            setError('Error saving content');
            console.error('Error saving content:', err);
        } finally {
            setIsSavingContent(false);
        }
    };

    const handleCancelEdit = () => {
        setEditContent(originalContent);
    };

    const hasContentChanged = editContent !== originalContent;

    const formatFileSize = (bytes: number | null) => {
        if (!bytes) return 'N/A';
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    return (
        <div className="space-y-6 max-h-[60vh] overflow-y-auto pr-2">
            <div className="space-y-2">
                <Label className="text-base font-semibold">Knowledge Base</Label>
                <p className="text-sm text-muted-foreground">
                    Enable knowledge base integration to allow the agent to search and retrieve
                    information from your organization&apos;s documents during conversations.
                </p>
            </div>

            {/* Enable toggle */}
            <div className="border rounded-lg p-4 space-y-4">
                <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-3">
                        <div className={`p-2 rounded-md ${config.enabled ? 'bg-green-500/10 text-green-600' : 'bg-muted text-muted-foreground'}`}>
                            <Book className="w-5 h-5" />
                        </div>
                        <div>
                            <Label htmlFor="kb-toggle" className="cursor-pointer font-medium">
                                Enable Knowledge Base
                            </Label>
                            <p className="text-xs text-muted-foreground">
                                Agent will search KB when it needs information
                            </p>
                        </div>
                    </div>
                    <Switch
                        id="kb-toggle"
                        checked={config.enabled}
                        onCheckedChange={handleToggle}
                    />
                </div>
            </div>

            {config.enabled && (
                <>
                    {/* Documents Section */}
                    <div className="space-y-3">
                        <div className="flex items-center justify-between">
                            <Label className="text-sm font-medium">Documents</Label>
                            <div className="flex gap-2">
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setShowAddForm(!showAddForm)}
                                >
                                    <Plus className="w-4 h-4 mr-1" />
                                    Add Text
                                </Button>
                                <label>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        disabled={isUploading}
                                        asChild
                                    >
                                        <span className="cursor-pointer">
                                            {isUploading ? (
                                                <Spinner size="sm" className="mr-1" />
                                            ) : (
                                                <Upload className="w-4 h-4 mr-1" />
                                            )}
                                            Upload File
                                        </span>
                                    </Button>
                                    <input
                                        type="file"
                                        className="hidden"
                                        accept=".txt,.md,.docx,.xlsx,.xls"
                                        onChange={handleFileUpload}
                                        disabled={isUploading}
                                    />
                                </label>
                            </div>
                        </div>

                        {error && (
                            <div className="p-3 bg-destructive/10 border border-destructive/20 rounded-md text-sm text-destructive">
                                {error}
                            </div>
                        )}

                        {/* Add Document Form */}
                        {showAddForm && (
                            <div className="border rounded-lg p-4 space-y-3 bg-muted/20">
                                <Input
                                    placeholder="Document name"
                                    value={newDocName}
                                    onChange={(e) => setNewDocName(e.target.value)}
                                />
                                <Textarea
                                    placeholder="Paste your document content here..."
                                    value={newDocContent}
                                    onChange={(e) => setNewDocContent(e.target.value)}
                                    className="min-h-[120px]"
                                />
                                <div className="flex gap-2 justify-end">
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        onClick={() => {
                                            setShowAddForm(false);
                                            setNewDocName('');
                                            setNewDocContent('');
                                        }}
                                    >
                                        Cancel
                                    </Button>
                                    <Button
                                        size="sm"
                                        onClick={handleAddDocument}
                                        disabled={isUploading}
                                    >
                                        {isUploading ? (
                                            <Spinner size="sm" className="mr-1" />
                                        ) : null}
                                        Add Document
                                    </Button>
                                </div>
                            </div>
                        )}

                        {/* Documents List */}
                        {isLoading ? (
                            <div className="flex items-center justify-center py-8">
                                <Spinner size="lg" />
                            </div>
                        ) : documents.length === 0 ? (
                            <div className="border border-dashed rounded-lg p-6 text-center">
                                <FileText className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                                <p className="text-sm text-muted-foreground">
                                    No documents yet. Upload a file or add text to get started.
                                </p>
                            </div>
                        ) : (
                            <div className="space-y-2">
                                {documents.map((doc) => (
                                    <div key={doc.id} className="border rounded-lg bg-card overflow-hidden">
                                        {/* Document header row */}
                                        <div
                                            className="flex items-center justify-between p-3 hover:bg-muted/30 transition-colors cursor-pointer"
                                            onClick={() => handleToggleExpand(doc.id)}
                                        >
                                            <div className="flex items-center gap-3 min-w-0">
                                                {expandedDocId === doc.id ? (
                                                    <ChevronDown className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                                                ) : (
                                                    <ChevronRight className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                                                )}
                                                <FileText className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                                                <div className="min-w-0">
                                                    <p className="text-sm font-medium truncate">{doc.name}</p>
                                                    <p className="text-xs text-muted-foreground">
                                                        {doc.chunk_count} chunks · {formatFileSize(doc.file_size_bytes)}
                                                        {doc.processing_status === 'processing' && (
                                                            <span className="ml-2 text-amber-500">Processing...</span>
                                                        )}
                                                        {doc.processing_status === 'error' && (
                                                            <span className="ml-2 text-destructive">Error</span>
                                                        )}
                                                    </p>
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-1 flex-shrink-0">
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    className="h-8 w-8 text-muted-foreground hover:text-foreground"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleToggleExpand(doc.id);
                                                    }}
                                                    title="Edit content"
                                                >
                                                    <Pencil className="w-3.5 h-3.5" />
                                                </Button>
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    className="h-8 w-8 text-muted-foreground hover:text-destructive"
                                                    onClick={(e) => { e.stopPropagation(); setDeleteDocId(doc.id); }}
                                                >
                                                    <Trash2 className="w-3.5 h-3.5" />
                                                </Button>
                                            </div>
                                        </div>

                                        {/* Expanded content editor */}
                                        {expandedDocId === doc.id && (
                                            <div className="border-t p-3 space-y-3 bg-muted/10">
                                                {isLoadingContent ? (
                                                    <div className="flex items-center justify-center py-8">
                                                        <Spinner size="md" />
                                                        <span className="ml-2 text-sm text-muted-foreground">
                                                            Loading content...
                                                        </span>
                                                    </div>
                                                ) : (
                                                    <>
                                                        <div className="flex items-center justify-between">
                                                            <Label className="text-xs font-medium text-muted-foreground">
                                                                Document Content
                                                                {hasContentChanged && (
                                                                    <span className="ml-2 text-amber-500">(unsaved changes)</span>
                                                                )}
                                                            </Label>
                                                            <span className="text-xs text-muted-foreground">
                                                                {editContent.length.toLocaleString()} characters
                                                            </span>
                                                        </div>
                                                        <Textarea
                                                            value={editContent}
                                                            onChange={(e) => setEditContent(e.target.value)}
                                                            className="min-h-[200px] max-h-[400px] font-mono text-sm"
                                                            placeholder="Document content..."
                                                        />
                                                        <div className="flex items-center justify-between">
                                                            <p className="text-xs text-muted-foreground">
                                                                Saving will re-process the document into chunks.
                                                            </p>
                                                            <div className="flex gap-2">
                                                                {hasContentChanged && (
                                                                    <Button
                                                                        variant="ghost"
                                                                        size="sm"
                                                                        onClick={handleCancelEdit}
                                                                        disabled={isSavingContent}
                                                                    >
                                                                        <X className="w-3.5 h-3.5 mr-1" />
                                                                        Discard
                                                                    </Button>
                                                                )}
                                                                <Button
                                                                    size="sm"
                                                                    onClick={handleSaveContent}
                                                                    disabled={!hasContentChanged || isSavingContent || !editContent.trim()}
                                                                >
                                                                    {isSavingContent ? (
                                                                        <Spinner size="sm" className="mr-1" />
                                                                    ) : (
                                                                        <Check className="w-3.5 h-3.5 mr-1" />
                                                                    )}
                                                                    {isSavingContent ? 'Saving...' : 'Save Content'}
                                                                </Button>
                                                            </div>
                                                        </div>
                                                    </>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* LLM Description */}
                    <div className="space-y-2">
                        <Label className="text-sm font-medium">LLM Description</Label>
                        <p className="text-xs text-muted-foreground">
                            Describe when and how the agent should use the knowledge base.
                        </p>
                        <Textarea
                            value={config.llm_description || ''}
                            onChange={(e) => setConfig({ ...config, llm_description: e.target.value })}
                            placeholder="Use the knowledge base when you need to look up information about products, policies, or procedures..."
                            className="min-h-[100px]"
                        />
                    </div>

                    {/* Query Override */}
                    <div className="space-y-2">
                        <Label className="text-sm font-medium">Query Override (Optional)</Label>
                        <p className="text-xs text-muted-foreground">
                            By default, the user&apos;s last message is used as the search query.
                            Provide a custom query if needed.
                        </p>
                        <Textarea
                            value={config.query_override || ''}
                            onChange={(e) => setConfig({ ...config, query_override: e.target.value })}
                            placeholder="Leave empty to use the user's last message as the query"
                            className="min-h-[60px]"
                        />
                    </div>

                    {/* Info box */}
                    <div className="flex items-start gap-3 p-4 border rounded-lg bg-primary/5 border-primary/20">
                        <Info className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
                        <div className="space-y-1">
                            <p className="text-sm font-medium text-primary">
                                How Knowledge Base Works
                            </p>
                            <p className="text-xs text-muted-foreground">
                                When enabled, the agent will automatically search your knowledge base
                                when it needs information. Documents are intelligently stored to provide
                                full context to the agent during conversations. Click on any document to
                                view and edit its content.
                            </p>
                        </div>
                    </div>
                </>
            )}

            {!config.enabled && (
                <div className="border border-dashed rounded-lg p-6 text-center">
                    <Book className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
                    <p className="text-sm text-muted-foreground">
                        Knowledge base is disabled. Enable it to allow the agent to search
                        your organization&apos;s documents during conversations.
                    </p>
                </div>
            )}

            <AlertDialog open={deleteDocId !== null} onOpenChange={(open) => { if (!open) setDeleteDocId(null); }}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Delete Document</AlertDialogTitle>
                        <AlertDialogDescription>
                            This will permanently delete this document and all its processed chunks. This action cannot be undone.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction
                            onClick={() => { if (deleteDocId !== null) handleDeleteDocument(deleteDocId); }}
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                        >
                            Delete
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}
