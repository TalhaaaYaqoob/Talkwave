"use client";

import 'react-international-phone/style.css';

import { AlertCircle, Globe, ExternalLink } from "lucide-react";

import { Spinner } from "@/components/ui/ai-loader";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { PhoneInput } from 'react-international-phone';

import {
    getTelephonyConfigurationApiV1OrganizationsTelephonyConfigGet,
    initiateCallApiV1TelephonyInitiateCallPost
} from '@/client/sdk.gen';
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useUserConfig } from "@/context/UserConfigContext";

// Error codes that indicate country/geo permission issues
const GEO_PERMISSION_ERROR_CODES = [21215, 21217, 21219];

interface CallError {
    error?: string;
    message?: string;
    reason?: string;
    code?: number;
    provider?: string;
}

function parseCallError(error: unknown): { message: string; isGeoError: boolean; isSubscriptionError: boolean; code?: number; provider?: string } {
    // Default error
    let message = "Failed to initiate call. Please try again.";
    let isGeoError = false;
    let isSubscriptionError = false;
    let code: number | undefined;
    let provider: string | undefined;

    if (typeof error === "string") {
        message = error;
    } else if (error && typeof error === "object") {
        const errObj = error as Record<string, unknown>;
        
        // Check if detail is a string (simple error)
        if (typeof errObj.detail === "string") {
            message = errObj.detail;
        } 
        // Check if detail is an object with structured error info
        else if (errObj.detail && typeof errObj.detail === "object") {
            const detail = errObj.detail as CallError;
            code = detail.code;
            provider = detail.provider;
            
            if (detail.message) {
                message = detail.message;
            } else if (detail.error) {
                message = detail.error;
            }
            
            // Check if this is a subscription limit error
            if (detail.error === "subscription_limit") {
                isSubscriptionError = true;
            }
            
            // Check if this is a geo permission error
            if (code && GEO_PERMISSION_ERROR_CODES.includes(code)) {
                isGeoError = true;
            }
        }
        // Fallback to direct message property
        else if (errObj.message && typeof errObj.message === "string") {
            message = errObj.message;
        }
    }

    return { message, isGeoError, isSubscriptionError, code, provider };
}

interface PhoneCallDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    workflowId: number;
    getAccessToken: () => Promise<string>;
    user: { id: string; email?: string };
}

export const PhoneCallDialog = ({
    open,
    onOpenChange,
    workflowId,
    getAccessToken,
    user,
}: PhoneCallDialogProps) => {
    const router = useRouter();
    const { userConfig, saveUserConfig, loading: userConfigLoading } = useUserConfig();
    const [phoneNumber, setPhoneNumber] = useState("");
    const [callLoading, setCallLoading] = useState(false);
    const [callError, setCallError] = useState<{ message: string; isGeoError: boolean; isSubscriptionError: boolean; code?: number; provider?: string } | null>(null);
    const [callSuccessMsg, setCallSuccessMsg] = useState<string | null>(null);
    const [phoneChanged, setPhoneChanged] = useState(false);
    const [checkingConfig, setCheckingConfig] = useState(false);
    const [needsConfiguration, setNeedsConfiguration] = useState<boolean | null>(null);

    // Check telephony configuration when dialog opens
    useEffect(() => {
        const checkConfig = async () => {
            if (!open) return;

            setCheckingConfig(true);
            try {
                const accessToken = await getAccessToken();
                const configResponse = await getTelephonyConfigurationApiV1OrganizationsTelephonyConfigGet({
                    headers: { 'Authorization': `Bearer ${accessToken}` },
                });

                if (configResponse.error || !configResponse.data?.twilio) {
                    setNeedsConfiguration(true);
                } else {
                    setNeedsConfiguration(false);
                }
            } catch (err) {
                console.error("Failed to check telephony config:", err);
                setNeedsConfiguration(false);
            } finally {
                setCheckingConfig(false);
            }
        };

        checkConfig();
    }, [open, getAccessToken]);

    // Reset state when dialog closes
    useEffect(() => {
        if (!open) {
            setCallError(null);
            setCallSuccessMsg(null);
            setCallLoading(false);
            setNeedsConfiguration(null);
        }
    }, [open]);

    // Track if we've initialized phone number for this dialog session
    const [initialized, setInitialized] = useState(false);
    
    // Initialize phone number when dialog opens and userConfig is ready
    useEffect(() => {
        if (open && !userConfigLoading && userConfig && !initialized) {
            const savedPhone = userConfig.test_phone_number || "";
            setPhoneNumber(savedPhone);
            setPhoneChanged(false);
            setCallError(null);
            setCallSuccessMsg(null);
            setCallLoading(false);
            setInitialized(true);
        }
        // Reset initialized when dialog closes
        if (!open) {
            setInitialized(false);
        }
    }, [open, userConfigLoading, userConfig, initialized]);

    const handlePhoneInputChange = (formattedValue: string) => {
        setPhoneNumber(formattedValue);
        setPhoneChanged(formattedValue !== userConfig?.test_phone_number);
        setCallError(null);
        setCallSuccessMsg(null);
    };

    const handleConfigureContinue = () => {
        onOpenChange(false);
        router.push('/telephony-configurations');
    };

    const handleStartCall = async () => {
        setCallLoading(true);
        setCallError(null);
        setCallSuccessMsg(null);
        try {
            if (!user || !userConfig) return;
            const accessToken = await getAccessToken();

            // Save phone number if it has changed
            if (phoneChanged) {
                await saveUserConfig({ ...userConfig, test_phone_number: phoneNumber });
                setPhoneChanged(false);
            }

            const response = await initiateCallApiV1TelephonyInitiateCallPost({
                body: {
                    workflow_id: workflowId,
                    phone_number: phoneNumber
                },
                headers: { 'Authorization': `Bearer ${accessToken}` },
            });

            if (response.error) {
                const parsedError = parseCallError(response.error);
                setCallError(parsedError);
            } else {
                const msg = response.data && (response.data as unknown as { message: string }).message || "Call initiated successfully!";
                setCallSuccessMsg(typeof msg === "string" ? msg : JSON.stringify(msg));
            }
        } catch (err: unknown) {
            const errorMessage = err instanceof Error ? err.message : "Failed to initiate call";
            setCallError({ message: errorMessage, isGeoError: false, isSubscriptionError: false });
        } finally {
            setCallLoading(false);
        }
    };

    // Render loading state
    const renderLoading = () => (
        <>
            <DialogHeader>
                <DialogTitle>Phone Call</DialogTitle>
            </DialogHeader>
            <div className="flex items-center justify-center py-8">
                <Spinner size="lg" />
            </div>
        </>
    );

    // Render configuration needed state
    const renderConfigurationNeeded = () => (
        <>
            <DialogHeader>
                <DialogTitle>Configure Telephony</DialogTitle>
                <DialogDescription>
                    You need to configure your telephony settings before making phone calls.
                    You will be redirected to the telephony configuration page.
                </DialogDescription>
            </DialogHeader>
            <DialogFooter>
                <Button variant="ghost" onClick={() => onOpenChange(false)}>
                    Do it Later
                </Button>
                <Button onClick={handleConfigureContinue}>
                    Continue
                </Button>
            </DialogFooter>
        </>
    );

    // Render error alert component
    const renderErrorAlert = () => {
        if (!callError) return null;

        if (callError.isSubscriptionError) {
            return (
                <Alert variant="destructive" className="mt-4 bg-amber-950/50 border-amber-500/30">
                    <AlertCircle className="h-4 w-4 text-amber-400" />
                    <AlertTitle className="text-amber-400">Subscription Limit Reached</AlertTitle>
                    <AlertDescription className="text-amber-300/80">
                        <p className="mb-3">{callError.message}</p>
                        <Button
                            variant="outline"
                            size="sm"
                            className="border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
                            onClick={() => {
                                onOpenChange(false);
                                router.push('/usage');
                            }}
                        >
                            View Usage
                        </Button>
                    </AlertDescription>
                </Alert>
            );
        }

        if (callError.isGeoError) {
            return (
                <Alert variant="destructive" className="mt-4 bg-red-950/50 border-red-500/30">
                    <Globe className="h-4 w-4" />
                    <AlertTitle className="text-red-400">Country Not Enabled</AlertTitle>
                    <AlertDescription className="text-red-300/80">
                        <p className="mb-3">{callError.message}</p>
                        <div className="bg-red-900/30 rounded-lg p-3 text-sm">
                            <p className="font-medium text-red-300 mb-2">How to fix this:</p>
                            <ol className="list-decimal list-inside space-y-1 text-red-300/70">
                                <li>Go to your Twilio Console</li>
                                <li>Navigate to Voice → Settings → Geo Permissions</li>
                                <li>Enable the country you want to call</li>
                                <li>Try making the call again</li>
                            </ol>
                            <a 
                                href="https://console.twilio.com/us1/develop/voice/settings/geo-permissions" 
                                target="_blank" 
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1.5 mt-3 text-red-400 hover:text-red-300 underline underline-offset-2"
                            >
                                Open Twilio Geo Permissions
                                <ExternalLink className="h-3 w-3" />
                            </a>
                        </div>
                    </AlertDescription>
                </Alert>
            );
        }

        return (
            <Alert variant="destructive" className="mt-4 bg-red-950/50 border-red-500/30">
                <AlertCircle className="h-4 w-4" />
                <AlertTitle className="text-red-400">Call Failed</AlertTitle>
                <AlertDescription className="text-red-300/80">
                    {callError.message}
                    {callError.code && (
                        <span className="ml-2 text-xs text-red-400/60">(Error code: {callError.code})</span>
                    )}
                </AlertDescription>
            </Alert>
        );
    };

    // Render phone call form
    const renderPhoneCallForm = () => (
        <>
            <DialogHeader>
                <DialogTitle>Phone Call</DialogTitle>
                <DialogDescription>
                    Enter the phone number to call. The number will be saved automatically.
                </DialogDescription>
            </DialogHeader>
            <PhoneInput
                defaultCountry="in"
                value={phoneNumber}
                onChange={handlePhoneInputChange}
            />
            <DialogFooter className="flex-col sm:flex-row gap-2">
                <Button
                    variant="outline"
                    onClick={() => {
                        onOpenChange(false);
                        router.push('/telephony-configurations');
                    }}
                >
                    Configure Telephony
                </Button>
                <div className="flex gap-2 flex-1 justify-end">
                    <DialogClose asChild>
                        <Button variant="outline">Cancel</Button>
                    </DialogClose>
                    {!callSuccessMsg ? (
                        <Button
                            onClick={handleStartCall}
                            disabled={callLoading || !phoneNumber}
                        >
                            {callLoading ? "Calling..." : "Start Call"}
                        </Button>
                    ) : (
                        <Button onClick={() => onOpenChange(false)}>
                            Close
                        </Button>
                    )}
                </div>
            </DialogFooter>
            {renderErrorAlert()}
            {callSuccessMsg && (
                <Alert className="mt-4 bg-green-950/50 border-green-500/30">
                    <AlertCircle className="h-4 w-4 text-green-400" />
                    <AlertDescription className="text-green-300/80">
                        {callSuccessMsg}
                    </AlertDescription>
                </Alert>
            )}
        </>
    );

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                {checkingConfig || userConfigLoading || needsConfiguration === null
                    ? renderLoading()
                    : needsConfiguration
                        ? renderConfigurationNeeded()
                        : renderPhoneCallForm()
                }
            </DialogContent>
        </Dialog>
    );
};
