'use client';

import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import { getUserConfigurationsApiV1UserConfigurationsUserGet, updateUserConfigurationsApiV1UserConfigurationsUserPut } from '@/client/sdk.gen';
import type { UserConfigurationRequestResponseSchema } from '@/client/types.gen';
import type { AuthUser } from '@/lib/auth';
import { useAuth } from '@/lib/auth';
import { getBackendUrl } from '@/lib/apiClient';


export type SaveUserConfigFunctionParams = {
    llm?: {
        [key: string]: string | number;
    } | null;
    tts?: {
        [key: string]: string | number;
    } | null;
    stt?: {
        [key: string]: string | number;
    } | null;
    test_phone_number?: string | null;
    timezone?: string | null;
};


interface TeamPermission {
    id: string;
}

interface OrganizationPricing {
    price_per_second_usd: number | null;
    currency: string;
    billing_enabled: boolean;
}

interface SubscriptionInfo {
    plan: string;
    status: string;
    billing_enabled: boolean;
    minutes_included: number;
    minutes_used: number;
    minutes_remaining: number;
    campaigns_enabled: boolean;
    custom_tools_enabled: boolean;
    gemini_s2s_enabled: boolean;
    trial_expired: boolean;
    max_workflows: number;
}

interface UserConfigContextType {
    userConfig: UserConfigurationRequestResponseSchema | null;
    saveUserConfig: (userConfig: SaveUserConfigFunctionParams) => Promise<void>;
    loading: boolean;
    error: Error | null;
    refreshConfig: () => Promise<void>;
    refreshSubscription: () => Promise<void>;
    permissions: TeamPermission[];
    accessToken: string | null;
    user: AuthUser | null;
    organizationPricing: OrganizationPricing | null;
    subscription: SubscriptionInfo | null;
}

const UserConfigContext = createContext<UserConfigContextType | null>(null);

export function UserConfigProvider({ children }: { children: ReactNode }) {
    const [userConfig, setUserConfig] = useState<UserConfigurationRequestResponseSchema | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);
    const [accessToken, setAccessToken] = useState<string | null>(null);
    const [organizationPricing, setOrganizationPricing] = useState<OrganizationPricing | null>(null);
    const [subscription, setSubscription] = useState<SubscriptionInfo | null>(null);
    const [permissions, setPermissions] = useState<TeamPermission[]>([]);

    const auth = useAuth();

    // Store auth functions in refs to avoid dependency issues
    const authRef = useRef(auth);
    authRef.current = auth;

    // Track initialization
    const hasFetchedConfig = useRef(false);
    const hasFetchedPermissions = useRef(false);

    // Fetch permissions once when auth is ready.
    useEffect(() => {
        if (auth.loading || hasFetchedPermissions.current) {
            return;
        }
        hasFetchedPermissions.current = true;

        const fetchPermissions = async () => {
            const currentAuth = authRef.current;
            if (currentAuth.provider === 'stack' && currentAuth.getSelectedTeam && currentAuth.listPermissions) {
                const selectedTeam = currentAuth.getSelectedTeam();
                if (selectedTeam) {
                    try {
                        const perms = await currentAuth.listPermissions(selectedTeam);
                        setPermissions(Array.isArray(perms) ? perms : []);
                    } catch {
                        setPermissions([]);
                    }
                } else {
                    setPermissions([]);
                }
            } else {
                setPermissions([{ id: 'admin' }]);
            }
        };

        fetchPermissions();
    }, [auth.loading, auth.provider]);

    // Fetch user config once when auth is ready - non-blocking
    useEffect(() => {
        if (auth.loading || !auth.isAuthenticated || hasFetchedConfig.current) {
            // If not authenticated yet, don't block - set loading false
            if (!auth.loading && !auth.isAuthenticated) {
                setLoading(false);
            }
            return;
        }
        hasFetchedConfig.current = true;

        const fetchUserConfig = async () => {
            try {
                const token = await authRef.current.getAccessToken();
                setAccessToken(token);

                const response = await getUserConfigurationsApiV1UserConfigurationsUserGet({
                    headers: {
                        'Authorization': `Bearer ${token}`,
                    },
                });

                if (response.data) {
                    setUserConfig(response.data);
                    if (response.data.organization_pricing) {
                        setOrganizationPricing({
                            price_per_second_usd: response.data.organization_pricing.price_per_second_usd as number | null,
                            currency: response.data.organization_pricing.currency as string || 'USD',
                            billing_enabled: response.data.organization_pricing.billing_enabled as boolean || false
                        });
                    } else {
                        setOrganizationPricing(null);
                    }
                }

                // Fire subscription fetch in background — don't await it
                const baseUrl = getBackendUrl();
                fetch(`${baseUrl}/api/v1/subscription/status`, {
                    headers: { 'Authorization': `Bearer ${token}` },
                }).then(async (subRes) => {
                    if (subRes.ok) {
                        const subData = await subRes.json();
                        setSubscription({
                            plan: subData.plan,
                            status: subData.status,
                            billing_enabled: subData.billing_enabled !== false,
                            minutes_included: subData.minutes_included,
                            minutes_used: subData.minutes_used,
                            minutes_remaining: subData.minutes_remaining,
                            campaigns_enabled: subData.campaigns_enabled,
                            custom_tools_enabled: subData.custom_tools_enabled,
                            gemini_s2s_enabled: subData.gemini_s2s_enabled,
                            trial_expired: subData.trial_expired,
                            max_workflows: subData.max_workflows,
                        });
                    }
                }).catch(() => {
                    // Subscription fetch is non-critical
                });

                setError(null);
            } catch (err) {
                setError(err instanceof Error ? err : new Error('Failed to fetch user configuration'));
                setAccessToken(null);
            } finally {
                setLoading(false);
            }
        };

        fetchUserConfig();
    }, [auth.loading, auth.isAuthenticated]);

    const saveUserConfig = useCallback(async (userConfigRequest: SaveUserConfigFunctionParams) => {
        if (!accessToken) throw new Error('No authentication token available');
        const response = await updateUserConfigurationsApiV1UserConfigurationsUserPut({
            body: {
                ...userConfig,
                ...userConfigRequest
            } as UserConfigurationRequestResponseSchema,
            headers: { 'Authorization': `Bearer ${accessToken}` },
        });
        if (response.error) {
            let msg = 'Failed to save user configuration';
            const detail = (response.error as unknown as { detail?: { errors: { model: string; message: string }[] } }).detail;
            if (Array.isArray(detail)) {
                msg = detail
                    .map((e: { model: string; message: string }) => `${e.model}: ${e.message}`)
                    .join('\n');
            }
            throw new Error(msg);
        }
        setUserConfig(response.data!);

        if (response.data?.organization_pricing) {
            setOrganizationPricing({
                price_per_second_usd: response.data.organization_pricing.price_per_second_usd as number | null,
                currency: response.data.organization_pricing.currency as string || 'USD',
                billing_enabled: response.data.organization_pricing.billing_enabled as boolean || false
            });
        }
    }, [accessToken, userConfig]);

    const refreshConfig = useCallback(async () => {
        const currentAuth = authRef.current;
        if (!currentAuth.isAuthenticated) return;

        setLoading(true);
        try {
            const token = await currentAuth.getAccessToken();
            setAccessToken(token);

            const response = await getUserConfigurationsApiV1UserConfigurationsUserGet({
                headers: {
                    'Authorization': `Bearer ${token}`,
                },
            });

            if (response.data) {
                setUserConfig(response.data);
                if (response.data.organization_pricing) {
                    setOrganizationPricing({
                        price_per_second_usd: response.data.organization_pricing.price_per_second_usd as number | null,
                        currency: response.data.organization_pricing.currency as string || 'USD',
                        billing_enabled: response.data.organization_pricing.billing_enabled as boolean || false
                    });
                }
            }
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err : new Error('Failed to fetch user configuration'));
        } finally {
            setLoading(false);
        }
    }, []);

    const refreshSubscription = useCallback(async () => {
        const currentAuth = authRef.current;
        if (!currentAuth.isAuthenticated) return;

        try {
            const token = await currentAuth.getAccessToken();
            const baseUrl = getBackendUrl();
            const subRes = await fetch(`${baseUrl}/api/v1/subscription/status`, {
                headers: { 'Authorization': `Bearer ${token}` },
            });
            if (subRes.ok) {
                const subData = await subRes.json();
                setSubscription({
                    plan: subData.plan,
                    status: subData.status,
                    billing_enabled: subData.billing_enabled !== false,
                    minutes_included: subData.minutes_included,
                    minutes_used: subData.minutes_used,
                    minutes_remaining: subData.minutes_remaining,
                    campaigns_enabled: subData.campaigns_enabled,
                    custom_tools_enabled: subData.custom_tools_enabled,
                    gemini_s2s_enabled: subData.gemini_s2s_enabled,
                    trial_expired: subData.trial_expired,
                    max_workflows: subData.max_workflows,
                });
            }
        } catch {
            // Non-critical
        }
    }, []);

    // Memoize context value to prevent unnecessary re-renders
    const contextValue = useMemo(() => ({
        userConfig,
        saveUserConfig,
        loading,
        error,
        refreshConfig,
        refreshSubscription,
        permissions,
        accessToken,
        user: auth.user,
        organizationPricing,
        subscription,
    }), [userConfig, saveUserConfig, loading, error, refreshConfig, refreshSubscription, permissions, accessToken, auth.user, organizationPricing, subscription]);

    return (
        <UserConfigContext.Provider value={contextValue}>
            {children}
        </UserConfigContext.Provider>
    );
}

export function useUserConfig() {
    const context = useContext(UserConfigContext);
    if (!context) {
        throw new Error('useUserConfig must be used within a UserConfigProvider');
    }
    return context;
}
