/**
 * Shared integration icon/color definitions.
 * Used by ToolsPanel (Agent Node), ActionsListPanel (Action Node),
 * ActionNode card preview, and the Integrations page.
 *
 * If you add a new integration, add it here and it will be reflected everywhere.
 */

import {
    Book,
    Calendar,
    CheckSquare,
    Database,
    FileSpreadsheet,
    Flame,
    Github,
    Globe,
    HardDrive,
    Hash,
    Mail,
    MessageCircle,
    Phone,
    Send,
    Table,
    Users,
    Variable,
    Webhook,
    Wrench,
    Zap,
} from 'lucide-react';

// Icon size helpers
export function icon(Icon: React.ComponentType<{ className?: string }>, size: string = 'w-5 h-5') {
    return <Icon className={size} />;
}

// ========================================================================
// Canonical integration definitions (icon, color, bgColor)
// ========================================================================

export interface IntegrationVisual {
    icon: (size?: string) => React.ReactNode;
    color: string;
    bgColor: string;
}

export const INTEGRATION_VISUALS: Record<string, IntegrationVisual> = {
    // -- Messaging --
    gmail: {
        icon: (s = 'w-5 h-5') => <Mail className={s} />,
        color: 'text-red-500',
        bgColor: 'bg-red-500/10 hover:bg-red-500/20 border-red-500/20',
    },
    slack: {
        icon: (s = 'w-5 h-5') => <Hash className={s} />,
        color: 'text-purple-500',
        bgColor: 'bg-purple-500/10 hover:bg-purple-500/20 border-purple-500/20',
    },
    twilio: {
        icon: (s = 'w-5 h-5') => <Phone className={s} />,
        color: 'text-pink-500',
        bgColor: 'bg-pink-500/10 hover:bg-pink-500/20 border-pink-500/20',
    },
    whatsapp: {
        icon: (s = 'w-5 h-5') => <MessageCircle className={s} />,
        color: 'text-green-500',
        bgColor: 'bg-green-500/10 hover:bg-green-500/20 border-green-500/20',
    },

    // -- Email providers (non-Gmail) --
    sendgrid: {
        icon: (s = 'w-5 h-5') => <Send className={s} />,
        color: 'text-blue-400',
        bgColor: 'bg-blue-400/10 hover:bg-blue-400/20 border-blue-400/20',
    },
    smtp: {
        icon: (s = 'w-5 h-5') => <Mail className={s} />,
        color: 'text-gray-400',
        bgColor: 'bg-gray-400/10 hover:bg-gray-400/20 border-gray-400/20',
    },
    mailgun: {
        icon: (s = 'w-5 h-5') => <Mail className={s} />,
        color: 'text-orange-500',
        bgColor: 'bg-orange-500/10 hover:bg-orange-500/20 border-orange-500/20',
    },

    // -- Productivity --
    googlesheets: {
        icon: (s = 'w-5 h-5') => <FileSpreadsheet className={s} />,
        color: 'text-emerald-500',
        bgColor: 'bg-emerald-500/10 hover:bg-emerald-500/20 border-emerald-500/20',
    },
    notion: {
        icon: (s = 'w-5 h-5') => <Book className={s} />,
        color: 'text-gray-100',
        bgColor: 'bg-gray-700/30 hover:bg-gray-700/40 border-gray-600/20',
    },
    airtable: {
        icon: (s = 'w-5 h-5') => <Table className={s} />,
        color: 'text-cyan-400',
        bgColor: 'bg-cyan-500/10 hover:bg-cyan-500/20 border-cyan-500/20',
    },
    googledrive: {
        icon: (s = 'w-5 h-5') => <HardDrive className={s} />,
        color: 'text-blue-400',
        bgColor: 'bg-blue-500/10 hover:bg-blue-500/20 border-blue-500/20',
    },
    googlecalendar: {
        icon: (s = 'w-5 h-5') => <Calendar className={s} />,
        color: 'text-blue-500',
        bgColor: 'bg-blue-500/10 hover:bg-blue-500/20 border-blue-500/20',
    },

    // -- CRM & Business --
    github: {
        icon: (s = 'w-5 h-5') => <Github className={s} />,
        color: 'text-gray-100',
        bgColor: 'bg-gray-700/30 hover:bg-gray-700/40 border-gray-600/20',
    },
    hubspot: {
        icon: (s = 'w-5 h-5') => <Users className={s} />,
        color: 'text-orange-500',
        bgColor: 'bg-orange-500/10 hover:bg-orange-500/20 border-orange-500/20',
    },
    linear: {
        icon: (s = 'w-5 h-5') => <CheckSquare className={s} />,
        color: 'text-indigo-400',
        bgColor: 'bg-indigo-500/10 hover:bg-indigo-500/20 border-indigo-500/20',
    },

    // -- Database --
    postgresql: {
        icon: (s = 'w-5 h-5') => <Database className={s} />,
        color: 'text-blue-600',
        bgColor: 'bg-blue-600/10 hover:bg-blue-600/20 border-blue-600/20',
    },
    mysql: {
        icon: (s = 'w-5 h-5') => <Database className={s} />,
        color: 'text-orange-500',
        bgColor: 'bg-orange-500/10 hover:bg-orange-500/20 border-orange-500/20',
    },
    mongodb: {
        icon: (s = 'w-5 h-5') => <Database className={s} />,
        color: 'text-green-600',
        bgColor: 'bg-green-600/10 hover:bg-green-600/20 border-green-600/20',
    },
    supabase: {
        icon: (s = 'w-5 h-5') => <Zap className={s} />,
        color: 'text-emerald-500',
        bgColor: 'bg-emerald-500/10 hover:bg-emerald-500/20 border-emerald-500/20',
    },
    firebase: {
        icon: (s = 'w-5 h-5') => <Flame className={s} />,
        color: 'text-amber-500',
        bgColor: 'bg-amber-500/10 hover:bg-amber-500/20 border-amber-500/20',
    },
    redis: {
        icon: (s = 'w-5 h-5') => <Zap className={s} />,
        color: 'text-red-600',
        bgColor: 'bg-red-600/10 hover:bg-red-600/20 border-red-600/20',
    },

    // -- API & Webhooks --
    http_api: {
        icon: (s = 'w-5 h-5') => <Globe className={s} />,
        color: 'text-violet-500',
        bgColor: 'bg-violet-500/10 hover:bg-violet-500/20 border-violet-500/20',
    },
    webhook: {
        icon: (s = 'w-5 h-5') => <Webhook className={s} />,
        color: 'text-amber-500',
        bgColor: 'bg-amber-500/10 hover:bg-amber-500/20 border-amber-500/20',
    },

    // -- Utility --
    set_variable: {
        icon: (s = 'w-5 h-5') => <Variable className={s} />,
        color: 'text-cyan-500',
        bgColor: 'bg-cyan-500/10 hover:bg-cyan-500/20 border-cyan-500/20',
    },
    custom_tool: {
        icon: (s = 'w-5 h-5') => <Wrench className={s} />,
        color: 'text-blue-500',
        bgColor: 'bg-blue-500/10 hover:bg-blue-500/20 border-blue-500/20',
    },
};

/** Get visual for a given key. Falls back to a generic Zap icon. */
export function getVisual(key: string): IntegrationVisual {
    return INTEGRATION_VISUALS[key] || {
        icon: (s = 'w-5 h-5') => <Zap className={s} />,
        color: 'text-muted-foreground',
        bgColor: 'bg-muted/10 hover:bg-muted/20 border-muted/20',
    };
}
