import type { CreateClientConfig } from '@/client/client.gen';

/**
 * Returns the backend base URL, enforcing HTTPS when the page is served
 * over HTTPS to prevent mixed-content browser errors.
 */
export function getBackendUrl(): string {
    if (typeof window === 'undefined') {
        return process.env.BACKEND_URL || 'http://api:8000';
    }

    let url = process.env.NEXT_PUBLIC_BACKEND_URL || window.location.origin;

    if (window.location.protocol === 'https:' && url.startsWith('http://')) {
        url = url.replace('http://', 'https://');
    }

    return url.replace(/\/+$/, '');
}

export const createClientConfig: CreateClientConfig = (config) => ({
    ...config,
    baseUrl: getBackendUrl(),
});
