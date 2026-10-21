"use client";

import {
    AlertCircle,
    Book,
    Check,
    Cloud,
    Database,
    ExternalLink,
    Eye,
    EyeOff,
    FileSpreadsheet,
    Github,
    Globe,
    HardDrive,
    Hash,
    Mail,
    MessageCircle,
    Phone,
    Plug,
    Save,
    Search,
    Table,
    Trash2,
    Users,
    X,
    Zap,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getBackendUrl } from "@/lib/apiClient";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

// =============================================================================
// Types
// =============================================================================

interface AppInfo {
    id: string;
    name: string;
    description: string;
    category: string;
    icon: string;
    logo?: string;  // URL to the app's logo image
    color: string;
    auth_mode: string;
    is_connected: boolean;
    status: "ACTIVE" | "PENDING" | "FAILED" | "INACTIVE" | "NOT_CONNECTED";
    connected_at?: string;
}

interface CategoryInfo {
    id: string;
    name: string;
    description: string;
}

interface DatabaseStatus {
    is_configured: boolean;
    is_enabled: boolean;
}

// =============================================================================
// Icon Mapping
// =============================================================================

const ICON_MAP: Record<string, React.ReactNode> = {
    "mail": <Mail className="w-6 h-6" />,
    "hash": <Hash className="w-6 h-6" />,
    "phone": <Phone className="w-6 h-6" />,
    "message-circle": <MessageCircle className="w-6 h-6" />,
    "file-spreadsheet": <FileSpreadsheet className="w-6 h-6" />,
    "book": <Book className="w-6 h-6" />,
    "table": <Table className="w-6 h-6" />,
    "hard-drive": <HardDrive className="w-6 h-6" />,
    "database": <Database className="w-6 h-6" />,
    "github": <Github className="w-6 h-6" />,
    "check-square": <Zap className="w-6 h-6" />,
    "users": <Users className="w-6 h-6" />,
    "cloud": <Cloud className="w-6 h-6" />,
};

// =============================================================================
// App Credentials Config (for non-OAuth apps)
// =============================================================================

const APP_CREDENTIALS_CONFIG: Record<string, { fields: Array<{ key: string; label: string; type: string; required: boolean; placeholder?: string }> }> = {
    twilio: {
        fields: [
            { key: "account_sid", label: "Account SID", type: "text", required: true, placeholder: "ACxxxxxxxxxx" },
            { key: "auth_token", label: "Auth Token", type: "password", required: true, placeholder: "Your auth token" },
            { key: "phone_number", label: "Twilio Phone Number", type: "text", required: true, placeholder: "+1234567890" },
        ],
    },
    airtable: {
        fields: [
            { key: "api_key", label: "API Key / Personal Access Token", type: "password", required: true, placeholder: "patXXXXXXXXXX" },
            { key: "base_id", label: "Default Base ID", type: "text", required: false, placeholder: "appXXXXXXXXXX" },
        ],
    },
    whatsapp: {
        fields: [
            { key: "account_sid", label: "Twilio Account SID", type: "text", required: true, placeholder: "ACxxxxxxxxxx" },
            { key: "auth_token", label: "Twilio Auth Token", type: "password", required: true, placeholder: "Your auth token" },
            { key: "from_number", label: "WhatsApp From Number", type: "text", required: true, placeholder: "whatsapp:+14155238886" },
        ],
    },
    supabase: {
        fields: [
            { key: "project_id", label: "Project ID", type: "text", required: true, placeholder: "abcdefghijklm (from Supabase Dashboard > Settings > General)" },
            { key: "api_key", label: "Anon/Public Key", type: "password", required: true, placeholder: "eyJhbGciOiJIUzI1NiIs..." },
            { key: "service_role_key", label: "Service Role Key (optional)", type: "password", required: false, placeholder: "For admin operations" },
        ],
    },
    mysql: {
        fields: [
            { key: "host", label: "Host", type: "text", required: true, placeholder: "localhost" },
            { key: "port", label: "Port", type: "number", required: true, placeholder: "3306" },
            { key: "database", label: "Database Name", type: "text", required: true, placeholder: "my_database" },
            { key: "username", label: "Username", type: "text", required: true, placeholder: "root" },
            { key: "password", label: "Password", type: "password", required: true, placeholder: "Your password" },
        ],
    },
    mongodb: {
        fields: [
            { key: "connection_string", label: "Connection String", type: "password", required: true, placeholder: "mongodb+srv://user:pass@cluster.mongodb.net/mydb" },
            { key: "database", label: "Database Name", type: "text", required: true, placeholder: "my_database" },
        ],
    },
    firebase: {
        fields: [
            { key: "project_id", label: "Project ID", type: "text", required: true, placeholder: "my-project-id" },
            { key: "service_account_key", label: "Service Account Key (JSON)", type: "password", required: true, placeholder: "Paste your Firebase service account JSON" },
        ],
    },
};

// =============================================================================
// Database Configurations
// =============================================================================

const DATABASE_CONFIGS = {
    supabase: {
        name: "Supabase",
        description: "PostgreSQL database with built-in auth and storage",
        icon: <Database className="w-6 h-6" />,
        logo: "https://supabase.com/favicon/favicon-196x196.png",
        color: "#3ECF8E",
        fields: [
            { key: "project_id", label: "Project ID", type: "text", required: true, placeholder: "abcdefghijklm (from Supabase Dashboard > Settings > General)" },
            { key: "api_key", label: "Anon/Public Key", type: "password", required: true, placeholder: "eyJhbGciOiJIUzI1NiIs..." },
            { key: "service_role_key", label: "Service Role Key (optional)", type: "password", required: false, placeholder: "For admin operations" },
        ],
        docsUrl: "https://supabase.com/docs",
    },
    mysql: {
        name: "MySQL",
        description: "Execute queries on MySQL databases",
        icon: <Database className="w-6 h-6" />,
        logo: "https://labs.mysql.com/common/logos/mysql-logo.svg",
        color: "#4479A1",
        fields: [
            { key: "host", label: "Host", type: "text", required: true, placeholder: "localhost" },
            { key: "port", label: "Port", type: "number", required: true, placeholder: "3306" },
            { key: "database", label: "Database Name", type: "text", required: true, placeholder: "my_database" },
            { key: "username", label: "Username", type: "text", required: true, placeholder: "root" },
            { key: "password", label: "Password", type: "password", required: true, placeholder: "Your password" },
        ],
        docsUrl: "https://dev.mysql.com/doc/",
    },
    mongodb: {
        name: "MongoDB",
        description: "NoSQL document database for flexible data",
        icon: <Database className="w-6 h-6" />,
        logo: "https://www.mongodb.com/assets/images/global/favicon.ico",
        color: "#47A248",
        fields: [
            { key: "connection_string", label: "Connection String", type: "password", required: true, placeholder: "mongodb+srv://user:pass@cluster.mongodb.net/mydb" },
            { key: "database", label: "Database Name", type: "text", required: true, placeholder: "my_database" },
        ],
        docsUrl: "https://www.mongodb.com/docs/",
    },
    firebase: {
        name: "Firebase",
        description: "Google Firebase Realtime DB & Firestore",
        icon: <Database className="w-6 h-6" />,
        logo: "https://www.gstatic.com/devrel-devsite/prod/v0e0f589edd85502a40d78d7d0825db8ea5ef3b99ab4070381ee86977c9168730/firebase/images/favicon.png",
        color: "#FFCA28",
        fields: [
            { key: "project_id", label: "Project ID", type: "text", required: true, placeholder: "my-project-id" },
            { key: "service_account_key", label: "Service Account Key (JSON)", type: "password", required: true, placeholder: "Paste your Firebase service account JSON" },
        ],
        docsUrl: "https://firebase.google.com/docs",
    },
};

// =============================================================================
// Main Component
// =============================================================================

import { AILoader, Spinner } from "@/components/ui/ai-loader";

// How many apps to render per category before collapsing behind a "Show all"
// button. Keeps the page snappy when the Composio catalog contains hundreds of
// apps. The full list is always shown while searching.
const APPS_PER_CATEGORY_PREVIEW = 12;

export default function IntegrationsPage() {
    const { user, getAccessToken, redirectToLogin, loading } = useAuth();
    const searchParams = useSearchParams();

    // State
    const [apps, setApps] = useState<AppInfo[]>([]);
    const [categories, setCategories] = useState<CategoryInfo[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [successMessage, setSuccessMessage] = useState<string | null>(null);
    const [activeTab, setActiveTab] = useState("apps");
    const [search, setSearch] = useState("");
    // Categories the user has expanded to reveal the full app list. Without
    // this, a large Composio catalog would render hundreds of rows at once and
    // make the page load as one heavy chunk.
    const [expandedCategories, setExpandedCategories] = useState<Record<string, boolean>>({});

    // Database state
    const [databaseStatuses, setDatabaseStatuses] = useState<Record<string, DatabaseStatus>>({});
    const [selectedDatabase, setSelectedDatabase] = useState<string | null>(null);
    const [dbFormData, setDbFormData] = useState<Record<string, string>>({});
    const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});
    const [isSavingDb, setIsSavingDb] = useState(false);
    const [dbDialogOpen, setDbDialogOpen] = useState(false);

    // App credentials dialog state
    const [appCredentialsDialogOpen, setAppCredentialsDialogOpen] = useState(false);
    const [selectedApp, setSelectedApp] = useState<AppInfo | null>(null);
    const [appFormData, setAppFormData] = useState<Record<string, string>>({});
    const [isSavingApp, setIsSavingApp] = useState(false);

    // Connection state
    const [connectingApp, setConnectingApp] = useState<string | null>(null);
    const [disconnectingApp, setDisconnectingApp] = useState<string | null>(null);

    // Redirect if not authenticated
    useEffect(() => {
        if (!loading && !user) {
            redirectToLogin();
        }
    }, [loading, user, redirectToLogin]);

    // Fetch apps and categories - PARALLELIZED for better performance
    const fetchData = useCallback(async () => {
        try {
            const token = await getAccessToken();
            
            // Fetch apps, categories, and all database statuses in PARALLEL
            const dbTypes = Object.keys(DATABASE_CONFIGS);
            const [appsRes, catsRes, ...dbResponses] = await Promise.all([
                fetch(`${getBackendUrl()}/api/v1/composio/apps`, {
                    headers: { Authorization: `Bearer ${token}` },
                }),
                fetch(`${getBackendUrl()}/api/v1/composio/categories`, {
                    headers: { Authorization: `Bearer ${token}` },
                }),
                ...dbTypes.map(dbType =>
                    fetch(`${getBackendUrl()}/api/v1/composio/database/${dbType}/status`, {
                        headers: { Authorization: `Bearer ${token}` },
                    })
                )
            ]);

            // Process responses in parallel
            const [appsData, catsData, ...dbDataArray] = await Promise.all([
                appsRes.ok ? appsRes.json() : null,
                catsRes.ok ? catsRes.json() : null,
                ...dbResponses.map(res => res.ok ? res.json() : null)
            ]);

            if (appsData) setApps(appsData);
            if (catsData) setCategories(catsData);
            
            // Set all database statuses at once
            const newDbStatuses: Record<string, DatabaseStatus> = {};
            dbTypes.forEach((dbType, index) => {
                if (dbDataArray[index]) {
                    newDbStatuses[dbType] = dbDataArray[index];
                }
            });
            setDatabaseStatuses(newDbStatuses);
        } catch (err) {
            console.error("Failed to fetch data:", err);
            setError("Failed to load integrations");
        } finally {
            setIsLoading(false);
        }
    }, [getAccessToken]);

    useEffect(() => {
        if (user) {
            fetchData();
        }
    }, [user, fetchData]);

    // Handle OAuth callback (when user returns from OAuth provider)
    useEffect(() => {
        const connectedApp = searchParams.get("connected");
        if (connectedApp) {
            // Clear the URL params
            window.history.replaceState({}, "", "/integrations");
            
            // Show success and refresh data
            setSuccessMessage(`${connectedApp} connected successfully!`);
            fetchData();
            setTimeout(() => setSuccessMessage(null), 5000);
        }
    }, [searchParams, fetchData]);

    // Connect app
    const handleConnect = async (app: AppInfo) => {
        // For apps needing credentials, open dialog
        if (app.auth_mode === "api_key" || app.auth_mode === "credentials" || APP_CREDENTIALS_CONFIG[app.id]) {
            setSelectedApp(app);
            setAppFormData({});
            setShowPasswords({});
            setError(null);
            setAppCredentialsDialogOpen(true);
            return;
        }

        // OAuth flow
        setConnectingApp(app.id);
        setError(null);

        try {
            const token = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/composio/connect`, {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${token}`,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    app_id: app.id,
                    redirect_url: `${window.location.origin}/integrations?connected=${app.id}`,
                }),
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || "Failed to initiate connection");
            }

            const data = await response.json();
            
            if (data.requires_credentials && app.auth_mode !== "oauth") {
                // Need to show credentials form (API-key based apps only)
                setSelectedApp(app);
                setAppFormData({});
                setShowPasswords({});
                setAppCredentialsDialogOpen(true);
            } else if (data.redirect_url) {
                // Redirect to OAuth
                window.location.href = data.redirect_url;
        } else {
                // Direct connection successful
                setSuccessMessage(`${app.name} connected successfully!`);
                fetchData();
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to connect");
        } finally {
            setConnectingApp(null);
        }
    };

    // Save app credentials
    const handleSaveAppCredentials = async () => {
        if (!selectedApp) return;

        const config = APP_CREDENTIALS_CONFIG[selectedApp.id];
        if (config) {
            const missingFields = config.fields
                .filter(f => f.required && !appFormData[f.key]?.trim())
                .map(f => f.label);

            if (missingFields.length > 0) {
                setError(`Missing required fields: ${missingFields.join(", ")}`);
                return;
            }
        }

        setIsSavingApp(true);
        setError(null);

        try {
            const token = await getAccessToken();
            const isDatabaseApp = ["supabase", "mysql", "mongodb", "firebase"].includes(selectedApp.id);

            if (isDatabaseApp) {
                // For Supabase: construct project_url from project_id
                const credentials = { ...appFormData };
                if (selectedApp.id === "supabase" && credentials.project_id) {
                    const pid = credentials.project_id.trim().replace(/^https?:\/\//, "").replace(/\.supabase\.co\/?$/, "");
                    credentials.project_url = `https://${pid}.supabase.co`;
                }

                // Save via database credentials endpoint (stores to both integration_ and composio_credentials_ keys)
                const response = await fetch(`${getBackendUrl()}/api/v1/composio/database/credentials`, {
                    method: "POST",
                    headers: {
                        Authorization: `Bearer ${token}`,
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        database_type: selectedApp.id,
                        credentials,
                        is_enabled: true,
                    }),
                });

                if (!response.ok) {
                    throw new Error("Failed to save credentials");
                }
            } else {
                const response = await fetch(`${getBackendUrl()}/api/v1/composio/connect`, {
                    method: "POST",
                    headers: {
                        Authorization: `Bearer ${token}`,
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        app_id: selectedApp.id,
                        credentials: appFormData,
                    }),
                });

                if (!response.ok) {
                    throw new Error("Failed to save credentials");
                }
            }

            setSuccessMessage(`${selectedApp.name} connected successfully!`);
            setAppCredentialsDialogOpen(false);
            fetchData();
            setTimeout(() => setSuccessMessage(null), 3000);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to save");
        } finally {
            setIsSavingApp(false);
        }
    };

    // Disconnect app
    const handleDisconnect = async (appId: string) => {
        setDisconnectingApp(appId);
        setError(null);

        try {
            const token = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/composio/disconnect`, {
                method: "POST",
            headers: {
                    Authorization: `Bearer ${token}`,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ app_id: appId }),
            });

            if (!response.ok) {
                throw new Error("Failed to disconnect");
            }

            setSuccessMessage("Disconnected successfully!");
            fetchData();
            setTimeout(() => setSuccessMessage(null), 3000);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to disconnect");
        } finally {
            setDisconnectingApp(null);
        }
    };

    // Save database credentials
    const handleSaveDatabase = async () => {
        if (!selectedDatabase) return;

        const config = DATABASE_CONFIGS[selectedDatabase as keyof typeof DATABASE_CONFIGS];
        const missingFields = config.fields
            .filter(f => f.required && !dbFormData[f.key]?.trim())
            .map(f => f.label);

        if (missingFields.length > 0) {
            setError(`Missing required fields: ${missingFields.join(", ")}`);
            return;
        }

        setIsSavingDb(true);
        setError(null);

        try {
            const token = await getAccessToken();

            // For Supabase: construct project_url from project_id
            const credentials = { ...dbFormData };
            if (selectedDatabase === "supabase" && credentials.project_id) {
                const pid = credentials.project_id.trim().replace(/^https?:\/\//, "").replace(/\.supabase\.co\/?$/, "");
                credentials.project_url = `https://${pid}.supabase.co`;
            }

            const response = await fetch(`${getBackendUrl()}/api/v1/composio/database/credentials`, {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${token}`,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    database_type: selectedDatabase,
                    credentials,
                    is_enabled: true,
                }),
            });

            if (!response.ok) {
                throw new Error("Failed to save credentials");
            }

            setSuccessMessage(`${config.name} configured successfully!`);
            setDbDialogOpen(false);
            fetchData();
            setTimeout(() => setSuccessMessage(null), 3000);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to save");
        } finally {
            setIsSavingDb(false);
        }
    };

    // Delete database credentials
    const handleDeleteDatabase = async (dbType: string) => {
        try {
            const token = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/composio/database/${dbType}`, {
                method: "DELETE",
                headers: { Authorization: `Bearer ${token}` },
            });

            if (response.ok) {
                setSuccessMessage("Database disconnected successfully!");
                fetchData();
                setTimeout(() => setSuccessMessage(null), 3000);
            }
        } catch (err) {
            setError("Failed to disconnect database");
        }
    };

    // Open database config dialog
    const openDatabaseDialog = (dbType: string) => {
        setSelectedDatabase(dbType);
        setDbFormData({});
        setShowPasswords({});
        setError(null);
        setDbDialogOpen(true);
    };

    // Get apps by category, applying the current search filter
    const getAppsByCategory = (categoryId: string) => {
        const q = search.trim().toLowerCase();
        return apps.filter(app => {
            if (app.category !== categoryId) return false;
            if (!q) return true;
            return (
                app.name.toLowerCase().includes(q) ||
                app.description.toLowerCase().includes(q) ||
                app.id.toLowerCase().includes(q)
            );
        });
    };

    const totalFilteredApps = (() => {
        const q = search.trim().toLowerCase();
        if (!q) return apps.length;
        return apps.filter(app =>
            app.name.toLowerCase().includes(q) ||
            app.description.toLowerCase().includes(q) ||
            app.id.toLowerCase().includes(q)
        ).length;
    })();

    // Render app row
    const renderAppRow = (app: AppInfo) => {
        const fallbackIcon = ICON_MAP[app.icon] || <Globe className="w-5 h-5" />;
        const isConnecting = connectingApp === app.id;
        const isDisconnecting = disconnectingApp === app.id;
        const isActive = app.status === "ACTIVE" || app.is_connected;
        const isPending = app.status === "PENDING";

        return (
            <div
                key={app.id}
                className={cn(
                    "group flex items-center gap-4 px-4 py-3.5 rounded-xl transition-all",
                    isActive
                        ? "bg-white/[0.04] ring-1 ring-primary/20"
                        : "hover:bg-white/[0.03]"
                )}
            >
                {/* Logo / Icon */}
                <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0 overflow-hidden"
                    style={{ backgroundColor: `${app.color}12` }}
                >
                    {app.logo ? (
                        <img
                            src={app.logo}
                            alt={app.name}
                            className="w-6 h-6 object-contain"
                            onError={(e) => {
                                e.currentTarget.style.display = 'none';
                                e.currentTarget.nextElementSibling?.classList.remove('hidden');
                            }}
                        />
                    ) : null}
                    <span style={{ color: app.color }} className={cn("flex items-center justify-center", app.logo && "hidden")}>
                        {fallbackIcon}
                    </span>
                </div>

                {/* Text */}
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white/90 truncate">{app.name}</span>
                        {isActive && <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />}
                        {isPending && <Spinner size="sm" className="shrink-0" />}
                    </div>
                    <p className="text-[11px] text-muted-foreground truncate leading-relaxed">{app.description}</p>
                    {isActive && app.connected_at && (
                        <p className="text-[10px] text-muted-foreground/60 mt-0.5">
                            Since {new Date(app.connected_at).toLocaleDateString()}
                        </p>
                    )}
                </div>

                {/* Action */}
                <div className="shrink-0">
                    {isActive ? (
                        <button
                            onClick={() => handleDisconnect(app.id)}
                            disabled={isDisconnecting}
                            className="text-[11px] text-red-400/70 hover:text-red-400 hover:bg-red-500/10 px-3 py-1.5 rounded-md transition-colors disabled:opacity-50"
                        >
                            {isDisconnecting ? <Spinner size="sm" /> : "Disconnect"}
                        </button>
                    ) : isPending ? (
                        <span className="text-[11px] text-amber-400/80 px-3 py-1.5">Connecting...</span>
                    ) : (
                        <button
                            onClick={() => handleConnect(app)}
                            disabled={isConnecting}
                            className="text-[11px] font-medium text-primary hover:text-primary/80 bg-primary/10 hover:bg-primary/15 px-3.5 py-1.5 rounded-md transition-colors disabled:opacity-50"
                        >
                            {isConnecting ? <Spinner size="sm" /> : "Connect"}
                        </button>
                    )}
                </div>
            </div>
        );
    };

    // Render database row
    const renderDatabaseRow = (dbType: string) => {
        const config = DATABASE_CONFIGS[dbType as keyof typeof DATABASE_CONFIGS];
        const status = databaseStatuses[dbType];
        const isConfigured = status?.is_configured;

        return (
            <div
                key={dbType}
                className={cn(
                    "group flex items-center gap-4 px-4 py-3.5 rounded-xl transition-all",
                    isConfigured
                        ? "bg-white/[0.04] ring-1 ring-primary/20"
                        : "hover:bg-white/[0.03] cursor-pointer"
                )}
                onClick={() => !isConfigured && openDatabaseDialog(dbType)}
            >
                <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0 overflow-hidden"
                    style={{ backgroundColor: `${config.color}12` }}
                >
                    {config.logo ? (
                        <img
                            src={config.logo}
                            alt={config.name}
                            className="w-6 h-6 object-contain"
                            onError={(e) => {
                                e.currentTarget.style.display = 'none';
                                e.currentTarget.nextElementSibling?.classList.remove('hidden');
                            }}
                        />
                    ) : null}
                    <span style={{ color: config.color }} className={cn("flex items-center justify-center", config.logo && "hidden")}>
                        {config.icon}
                    </span>
                </div>

                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white/90 truncate">{config.name}</span>
                        {isConfigured && <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />}
                    </div>
                    <p className="text-[11px] text-muted-foreground truncate leading-relaxed">{config.description}</p>
                </div>

                <div className="shrink-0 flex items-center gap-1.5">
                    {isConfigured ? (
                        <>
                            <button
                                onClick={(e) => { e.stopPropagation(); openDatabaseDialog(dbType); }}
                                className="text-[11px] text-muted-foreground hover:text-white/80 hover:bg-white/[0.06] px-3 py-1.5 rounded-md transition-colors"
                            >
                                Update
                            </button>
                            <button
                                onClick={(e) => { e.stopPropagation(); handleDeleteDatabase(dbType); }}
                                className="text-red-400/70 hover:text-red-400 hover:bg-red-500/10 p-1.5 rounded-md transition-colors"
                            >
                                <Trash2 className="w-3.5 h-3.5" />
                            </button>
                        </>
                    ) : (
                        <button className="text-[11px] font-medium text-primary hover:text-primary/80 bg-primary/10 hover:bg-primary/15 px-3.5 py-1.5 rounded-md transition-colors">
                            Connect
                        </button>
                    )}
                </div>
            </div>
        );
    };

    // Only block the whole page on auth. The app catalog can be large/slow, so
    // we render the page shell immediately and show an inline loader in the
    // Apps tab instead of freezing the entire page behind a full-screen spinner.
    if (loading) {
        return <AILoader />;
    }

    const connectedAppsCount = apps.filter(a => a.is_connected || a.status === "ACTIVE").length;
    const connectedDbCount = Object.values(databaseStatuses).filter(s => s.is_configured).length;

    return (
        <div className="max-w-3xl mx-auto px-4 py-10">
            {/* Header */}
            <div className="mb-8">
                <h1 className="text-2xl font-semibold tracking-tight">Integrations</h1>
                <p className="text-sm text-muted-foreground mt-1">
                    Connect apps and databases to your AI workflows
                </p>
            </div>

            {/* Status pills */}
            <div className="flex items-center gap-3 mb-8">
                <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-400 bg-emerald-500/10 px-2.5 py-1 rounded-full">
                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    {connectedAppsCount} app{connectedAppsCount !== 1 ? "s" : ""} connected
                </span>
                <span className="inline-flex items-center gap-1.5 text-xs font-medium text-primary bg-primary/10 px-2.5 py-1 rounded-full">
                    <Database className="w-3 h-3" />
                    {connectedDbCount} database{connectedDbCount !== 1 ? "s" : ""}
                </span>
            </div>

            {/* Toasts */}
            {successMessage && (
                <div className="mb-6 flex items-center gap-2.5 px-4 py-3 rounded-lg bg-emerald-500/10 ring-1 ring-emerald-500/20">
                    <Check className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span className="text-sm text-emerald-300 flex-1">{successMessage}</span>
                    <button onClick={() => setSuccessMessage(null)} className="text-emerald-400/60 hover:text-emerald-400">
                        <X className="w-3.5 h-3.5" />
                    </button>
                </div>
            )}
            {error && (
                <div className="mb-6 flex items-center gap-2.5 px-4 py-3 rounded-lg bg-red-500/10 ring-1 ring-red-500/20">
                    <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
                    <span className="text-sm text-red-300 flex-1">{error}</span>
                    <button onClick={() => setError(null)} className="text-red-400/60 hover:text-red-400">
                        <X className="w-3.5 h-3.5" />
                    </button>
                </div>
            )}

            {/* Tabs */}
            <Tabs value={activeTab} onValueChange={setActiveTab}>
                <TabsList className="bg-white/[0.04] border border-white/[0.06] rounded-lg p-0.5 mb-8 inline-flex">
                    <TabsTrigger
                        value="apps"
                        className="text-xs data-[state=active]:bg-white/[0.08] data-[state=active]:text-white rounded-md px-4 py-1.5"
                    >
                        Apps
                    </TabsTrigger>
                    <TabsTrigger
                        value="databases"
                        className="text-xs data-[state=active]:bg-white/[0.08] data-[state=active]:text-white rounded-md px-4 py-1.5"
                    >
                        Databases
                    </TabsTrigger>
                </TabsList>

                {/* Apps Tab */}
                <TabsContent value="apps" className="space-y-8 mt-0">
                    {/* Search */}
                    <div className="relative">
                        <Search className="w-4 h-4 text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2" />
                        <Input
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Search apps (Gmail, Slack, HubSpot, Jira…)"
                            className="pl-9"
                        />
                        {search && (
                            <button
                                onClick={() => setSearch("")}
                                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                            >
                                <X className="w-3.5 h-3.5" />
                            </button>
                        )}
                    </div>

                    {isLoading && (
                        <div className="flex flex-col items-center justify-center py-16 gap-3">
                            <Spinner size="lg" />
                            <p className="text-xs text-muted-foreground">Loading apps…</p>
                        </div>
                    )}

                    {!isLoading && categories.map((category) => {
                        const categoryApps = getAppsByCategory(category.id);
                        if (categoryApps.length === 0) return null;

                        // Show everything while searching; otherwise cap the
                        // preview so large categories don't render all at once.
                        const isSearching = search.trim().length > 0;
                        const isExpanded = isSearching || expandedCategories[category.id];
                        const visibleApps = isExpanded
                            ? categoryApps
                            : categoryApps.slice(0, APPS_PER_CATEGORY_PREVIEW);
                        const hiddenCount = categoryApps.length - visibleApps.length;

                        return (
                            <div key={category.id}>
                                <div className="flex items-baseline gap-2 mb-3 px-1">
                                    <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{category.name}</h2>
                                    <span className="text-[10px] text-muted-foreground/50">{categoryApps.length}</span>
                                </div>
                                <div className="rounded-xl bg-white/[0.02] ring-1 ring-white/[0.06] divide-y divide-white/[0.04]">
                                    {visibleApps.map(renderAppRow)}
                                </div>
                                {hiddenCount > 0 && (
                                    <button
                                        onClick={() => setExpandedCategories(prev => ({ ...prev, [category.id]: true }))}
                                        className="mt-2 w-full text-center text-[11px] font-medium text-primary hover:text-primary/80 py-2 rounded-lg hover:bg-primary/5 transition-colors"
                                    >
                                        Show all {categoryApps.length} apps
                                    </button>
                                )}
                                {!isSearching && isExpanded && categoryApps.length > APPS_PER_CATEGORY_PREVIEW && (
                                    <button
                                        onClick={() => setExpandedCategories(prev => ({ ...prev, [category.id]: false }))}
                                        className="mt-2 w-full text-center text-[11px] font-medium text-muted-foreground hover:text-white/80 py-2 rounded-lg hover:bg-white/[0.04] transition-colors"
                                    >
                                        Show less
                                    </button>
                                )}
                            </div>
                        );
                    })}

                    {!isLoading && apps.length === 0 && (
                        <div className="text-center py-16">
                            <Plug className="w-8 h-8 text-muted-foreground/40 mx-auto mb-3" />
                            <p className="text-sm text-muted-foreground">No apps available</p>
                        </div>
                    )}

                    {!isLoading && apps.length > 0 && totalFilteredApps === 0 && (
                        <div className="text-center py-16">
                            <Search className="w-8 h-8 text-muted-foreground/40 mx-auto mb-3" />
                            <p className="text-sm text-muted-foreground">
                                No apps match &ldquo;{search}&rdquo;
                            </p>
                        </div>
                    )}
                </TabsContent>

                {/* Databases Tab */}
                <TabsContent value="databases" className="mt-0">
                    <div className="flex items-baseline gap-2 mb-3 px-1">
                        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Database Connections</h2>
                    </div>
                    <div className="rounded-xl bg-white/[0.02] ring-1 ring-white/[0.06] divide-y divide-white/[0.04]">
                        {Object.keys(DATABASE_CONFIGS).map(renderDatabaseRow)}
                    </div>
                </TabsContent>
            </Tabs>

            {/* App Credentials Dialog */}
            <Dialog open={appCredentialsDialogOpen} onOpenChange={setAppCredentialsDialogOpen}>
                <DialogContent className="max-w-lg">
                    <DialogHeader>
                        {selectedApp && (
                            <div className="flex items-center gap-3">
                                <div
                                    className="p-2 rounded-lg border flex items-center justify-center overflow-hidden"
                                    style={{
                                        backgroundColor: `${selectedApp.color}10`,
                                        borderColor: `${selectedApp.color}30`,
                                        width: 48,
                                        height: 48,
                                    }}
                                >
                                    {selectedApp.logo ? (
                                        <img 
                                            src={selectedApp.logo} 
                                            alt={`${selectedApp.name} logo`}
                                            className="w-8 h-8 object-contain"
                                        />
                                    ) : (
                                        <span style={{ color: selectedApp.color }}>
                                            {ICON_MAP[selectedApp.icon] || <Globe className="w-6 h-6" />}
                                        </span>
                                    )}
                                </div>
                                <div>
                                    <DialogTitle>Connect {selectedApp.name}</DialogTitle>
                                    <DialogDescription>Enter your API credentials</DialogDescription>
                                </div>
                            </div>
                        )}
                    </DialogHeader>

                    <div className="space-y-4 py-4">
                        {selectedApp && APP_CREDENTIALS_CONFIG[selectedApp.id]?.fields.map((field) => (
                            <div key={field.key} className="space-y-2">
                                <Label htmlFor={field.key}>
                                    {field.label}
                                    {field.required && <span className="text-red-500 ml-1">*</span>}
                                </Label>
                                <div className="relative">
                                    <Input
                                        id={field.key}
                                        type={field.type === "password" && !showPasswords[field.key] ? "password" : "text"}
                                        value={appFormData[field.key] || ""}
                                        onChange={(e) => setAppFormData({ ...appFormData, [field.key]: e.target.value })}
                                        placeholder={field.placeholder}
                                        className={field.type === "password" ? "pr-10" : ""}
                                    />
                                    {field.type === "password" && (
                                        <button
                                            type="button"
                                            onClick={() => setShowPasswords({ ...showPasswords, [field.key]: !showPasswords[field.key] })}
                                            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                                        >
                                            {showPasswords[field.key] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                                        </button>
                                    )}
                                </div>
                            </div>
                        ))}

                        {/* Fallback for apps without predefined config */}
                        {selectedApp && !APP_CREDENTIALS_CONFIG[selectedApp.id] && (
                            <div className="space-y-2">
                                <Label htmlFor="api_key">
                                    API Key <span className="text-red-500">*</span>
                                </Label>
                                <div className="relative">
                                    <Input
                                        id="api_key"
                                        type={showPasswords["api_key"] ? "text" : "password"}
                                        value={appFormData["api_key"] || ""}
                                        onChange={(e) => setAppFormData({ ...appFormData, api_key: e.target.value })}
                                        placeholder="Enter your API key"
                                        className="pr-10"
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowPasswords({ ...showPasswords, api_key: !showPasswords["api_key"] })}
                                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                                    >
                                        {showPasswords["api_key"] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                                    </button>
                                </div>
                            </div>
                        )}

                        {error && (
                            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 flex items-center gap-2">
                                <AlertCircle className="w-4 h-4 text-red-500" />
                                <span className="text-sm text-red-600">{error}</span>
                            </div>
                        )}
                    </div>

                    <DialogFooter>
                        <Button variant="outline" onClick={() => setAppCredentialsDialogOpen(false)}>
                            Cancel
                        </Button>
                        <Button onClick={handleSaveAppCredentials} disabled={isSavingApp}>
                            {isSavingApp ? (
                                <Spinner size="sm" className="mr-2" />
                            ) : (
                                <Save className="w-4 h-4 mr-2" />
                            )}
                            Connect
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Database Config Dialog */}
            <Dialog open={dbDialogOpen} onOpenChange={setDbDialogOpen}>
                <DialogContent className="max-w-lg">
                    <DialogHeader>
                        {selectedDatabase && (
                            <div className="flex items-center gap-3">
                                <div
                                    className="p-2 rounded-lg border flex items-center justify-center overflow-hidden"
                                    style={{
                                        backgroundColor: `${DATABASE_CONFIGS[selectedDatabase as keyof typeof DATABASE_CONFIGS].color}10`,
                                        borderColor: `${DATABASE_CONFIGS[selectedDatabase as keyof typeof DATABASE_CONFIGS].color}30`,
                                        width: 48,
                                        height: 48,
                                    }}
                                >
                                    {DATABASE_CONFIGS[selectedDatabase as keyof typeof DATABASE_CONFIGS].logo ? (
                                        <img 
                                            src={DATABASE_CONFIGS[selectedDatabase as keyof typeof DATABASE_CONFIGS].logo} 
                                            alt={`${DATABASE_CONFIGS[selectedDatabase as keyof typeof DATABASE_CONFIGS].name} logo`}
                                            className="w-8 h-8 object-contain"
                                        />
                                    ) : (
                                        <span style={{ color: DATABASE_CONFIGS[selectedDatabase as keyof typeof DATABASE_CONFIGS].color }}>
                                            {DATABASE_CONFIGS[selectedDatabase as keyof typeof DATABASE_CONFIGS].icon}
                                        </span>
                                    )}
                                </div>
                                <div>
                                    <DialogTitle>
                                        Configure {DATABASE_CONFIGS[selectedDatabase as keyof typeof DATABASE_CONFIGS].name}
                                    </DialogTitle>
                                    <DialogDescription>
                                        {DATABASE_CONFIGS[selectedDatabase as keyof typeof DATABASE_CONFIGS].description}
                                    </DialogDescription>
                                </div>
                            </div>
                        )}
                    </DialogHeader>

                    <div className="space-y-4 py-4">
                        {selectedDatabase && DATABASE_CONFIGS[selectedDatabase as keyof typeof DATABASE_CONFIGS].fields.map((field) => (
                            <div key={field.key} className="space-y-2">
                                <Label htmlFor={field.key}>
                                    {field.label}
                                    {field.required && <span className="text-red-500 ml-1">*</span>}
                                </Label>
                                <div className="relative">
                                    <Input
                                        id={field.key}
                                        type={field.type === "password" && !showPasswords[field.key] ? "password" : field.type === "number" ? "number" : "text"}
                                        value={dbFormData[field.key] || ""}
                                        onChange={(e) => setDbFormData({ ...dbFormData, [field.key]: e.target.value })}
                                        placeholder={field.placeholder}
                                        className={field.type === "password" ? "pr-10" : ""}
                                    />
                                    {field.type === "password" && (
                                        <button
                                            type="button"
                                            onClick={() => setShowPasswords({ ...showPasswords, [field.key]: !showPasswords[field.key] })}
                                            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                                        >
                                            {showPasswords[field.key] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                                        </button>
                                    )}
                                </div>
                            </div>
                        ))}

                        {selectedDatabase && DATABASE_CONFIGS[selectedDatabase as keyof typeof DATABASE_CONFIGS].docsUrl && (
                            <a
                                href={DATABASE_CONFIGS[selectedDatabase as keyof typeof DATABASE_CONFIGS].docsUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="flex items-center gap-2 text-sm text-primary hover:underline"
                            >
                                <ExternalLink className="w-4 h-4" />
                                View Documentation
                            </a>
                        )}

                        {error && (
                            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 flex items-center gap-2">
                                <AlertCircle className="w-4 h-4 text-red-500" />
                                <span className="text-sm text-red-600">{error}</span>
                            </div>
                        )}
                    </div>

                    <DialogFooter>
                        <Button variant="outline" onClick={() => setDbDialogOpen(false)}>
                            Cancel
                        </Button>
                        <Button onClick={handleSaveDatabase} disabled={isSavingDb}>
                            {isSavingDb ? (
                                <Spinner size="sm" className="mr-2" />
                            ) : (
                                <Save className="w-4 h-4 mr-2" />
                            )}
                            Save
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Quick guide */}
            <div className="mt-12 rounded-xl bg-white/[0.02] ring-1 ring-white/[0.06] p-5">
                <div className="flex items-center gap-2 mb-4">
                    <Zap className="w-4 h-4 text-primary" />
                    <span className="text-sm font-medium">Quick Guide</span>
                </div>
                <div className="grid gap-4 sm:grid-cols-3">
                    <div className="space-y-1">
                        <p className="text-xs font-medium text-white/70">1. Connect</p>
                        <p className="text-[11px] text-muted-foreground leading-relaxed">
                            Authenticate via OAuth or enter API credentials
                        </p>
                    </div>
                    <div className="space-y-1">
                        <p className="text-xs font-medium text-white/70">2. Add to Agents</p>
                        <p className="text-[11px] text-muted-foreground leading-relaxed">
                            Select connected tools inside Agent or Action nodes
                        </p>
                    </div>
                    <div className="space-y-1">
                        <p className="text-xs font-medium text-white/70">3. Run</p>
                        <p className="text-[11px] text-muted-foreground leading-relaxed">
                            Your AI agent can now use these tools during calls
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
}
