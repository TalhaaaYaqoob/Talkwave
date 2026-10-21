'use client';

import Nango from '@nangohq/frontend';
import { useState } from 'react';
import { toast } from 'sonner';

import { createSessionApiV1IntegrationSessionPost } from "@/client/sdk.gen";
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth';
import logger from '@/lib/logger';


export default function CreateIntegrationButton() {
    const [isLoading, setIsLoading] = useState(false);
    const { user, getAccessToken, loading: authLoading } = useAuth();

    const handleCreateIntegration = async () => {
        setIsLoading(true);
        try {
            // Wait for auth to finish loading
            if (authLoading) {
                throw new Error('Authentication is still loading. Please wait and try again.');
            }
            
            if (!user) {
                throw new Error('User not authenticated. Please sign in first.');
            }
            const accessToken = await getAccessToken();

            // Fetch session details from our API
            const sessionResponse = await createSessionApiV1IntegrationSessionPost({
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
            });

            if (!sessionResponse.data?.session_token) {
                throw new Error('Failed to get session token');
            }

            // Initialize Nango and open connect UI
            const nango = new Nango();
            const connect = nango.openConnectUI({
                onEvent: (event) => {
                    if (event.type === 'close') {
                        // Handle modal closed
                        setIsLoading(false);
                        logger.info('Nango connect UI closed');
                    } else if (event.type === 'connect') {
                        // Handle auth flow successful
                        setIsLoading(false);
                        logger.info('Integration connected successfully');
                        // Refresh the page to show new integrations
                        window.location.reload();
                    }
                },
            });

            // Set the session token to initialize the connect UI
            connect.setSessionToken(sessionResponse.data.session_token);

        } catch (err) {
            logger.error(`Error creating integration: ${err}`);
            setIsLoading(false);
            toast.error('Failed to create integration. Please try again.');
        }
    };

    return (
        <Button onClick={handleCreateIntegration} disabled={isLoading || authLoading}>
            {authLoading ? 'Loading auth...' : isLoading ? 'Creating...' : 'Create Integration'}
        </Button>
    );
}
