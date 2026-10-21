import { ActionConfig } from '@/components/flow/types';

// Matches a {{ variable }} placeholder. We only treat a reference as
// "checkable" when the inner token is a plain identifier (letters, digits,
// underscores) — the same shape the backend template renderer substitutes
// (\w+). Anything with dots/spaces/expressions is left alone so we never flag a
// false positive.
const TEMPLATE_TOKEN_RE = /\{\{\s*([^}]+?)\s*\}\}/g;
const PLAIN_IDENTIFIER_RE = /^[a-zA-Z0-9_]+$/;

/**
 * Pull every checkable {{variable}} name out of a single string.
 */
export function extractTemplateVars(value: unknown): string[] {
    if (typeof value !== 'string' || !value) return [];
    const found: string[] = [];
    let m: RegExpExecArray | null;
    TEMPLATE_TOKEN_RE.lastIndex = 0;
    while ((m = TEMPLATE_TOKEN_RE.exec(value)) !== null) {
        const token = (m[1] || '').trim();
        if (PLAIN_IDENTIFIER_RE.test(token)) found.push(token);
    }
    return found;
}

/**
 * Recursively collect every {{variable}} reference from any string value
 * anywhere inside an action config (covers nested headers, data_mapping,
 * input_data, parameters, etc. without enumerating each field by hand).
 */
export function collectReferencedVars(value: unknown, acc: Set<string> = new Set()): Set<string> {
    if (typeof value === 'string') {
        for (const v of extractTemplateVars(value)) acc.add(v);
    } else if (Array.isArray(value)) {
        for (const item of value) collectReferencedVars(item, acc);
    } else if (value && typeof value === 'object') {
        for (const v of Object.values(value as Record<string, unknown>)) collectReferencedVars(v, acc);
    }
    return acc;
}

/**
 * Names that an action PRODUCES (so a downstream action referencing them isn't
 * flagged as stale): set_variable outputs, and api/db result holders.
 */
export function collectProducedVars(action: ActionConfig): string[] {
    const out: string[] = [];
    const a = action as unknown as Record<string, unknown>;
    const push = (n: unknown) => {
        if (typeof n === 'string' && n.trim()) out.push(n.trim());
    };
    if (action.type === 'set_variable') push(a.variable_name);
    if (action.type === 'api_call') push(a.response_variable);
    if (action.type === 'database_query') push(a.result_variable);
    return out;
}

export interface StaleRefResult {
    // Stale variable names per action id.
    byAction: Record<string, string[]>;
    // Flat, de-duplicated list of every stale variable name.
    all: string[];
}

/**
 * Find {{variable}} references in actions that aren't produced by any known
 * source: the workflow's available variables (extraction + exit-condition +
 * template context) plus variables produced by the actions themselves.
 */
export function findStaleActionRefs(
    actions: ActionConfig[],
    availableVariables: string[],
): StaleRefResult {
    const known = new Set<string>(availableVariables.map((v) => v.trim()).filter(Boolean));
    for (const action of actions) {
        for (const produced of collectProducedVars(action)) known.add(produced);
    }

    const byAction: Record<string, string[]> = {};
    const all = new Set<string>();

    for (const action of actions) {
        const refs = collectReferencedVars(action);
        const produced = new Set(collectProducedVars(action));
        const stale: string[] = [];
        for (const ref of refs) {
            // An action referencing the variable it itself produces is fine.
            if (produced.has(ref)) continue;
            if (!known.has(ref)) stale.push(ref);
        }
        if (stale.length > 0) {
            byAction[action.id] = stale;
            for (const s of stale) all.add(s);
        }
    }

    return { byAction, all: Array.from(all) };
}
