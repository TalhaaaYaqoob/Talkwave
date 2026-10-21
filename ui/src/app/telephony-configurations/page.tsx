"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { Phone, Key, CheckCircle2, ExternalLink, UserRound } from "lucide-react";

import { getTelephonyConfigurationApiV1OrganizationsTelephonyConfigGet, saveTelephonyConfigurationApiV1OrganizationsTelephonyConfigPost } from "@/client/sdk.gen";
import type { TwilioConfigurationRequest } from "@/client/types.gen";
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
import { useAuth } from "@/lib/auth";
import { useUserConfig } from "@/context/UserConfigContext";

interface TelephonyConfigForm {
  account_sid?: string;
  auth_token?: string;
  from_number: string;
  test_phone_number?: string;
}

export default function ConfigureTelephonyPage() {
  const { user, getAccessToken, loading: authLoading } = useAuth();
  const { userConfig, saveUserConfig, loading: userConfigLoading } = useUserConfig();
  const [isLoading, setIsLoading] = useState(false);
  const [hasExistingConfig, setHasExistingConfig] = useState(false);

  // Clean up any stale pointer-events from dialogs that weren't properly closed before navigation
  useEffect(() => {
    document.body.style.pointerEvents = '';
  }, []);

  const {
    register,
    handleSubmit,
    formState: { errors },
    setValue,
  } = useForm<TelephonyConfigForm>({
    defaultValues: {},
  });

  useEffect(() => {
    // Don't fetch config while auth is still loading
    if (authLoading || !user) {
      return;
    }

    // Fetch existing configuration with masked sensitive fields
    const fetchConfig = async () => {
      try {
        const accessToken = await getAccessToken();
        const response = await getTelephonyConfigurationApiV1OrganizationsTelephonyConfigGet({
          headers: { Authorization: `Bearer ${accessToken}` },
        });

        if (!response.error) {
          if (response.data?.twilio) {
            setHasExistingConfig(true);
            setValue("account_sid", response.data.twilio.account_sid);
            setValue("auth_token", response.data.twilio.auth_token);
            if (response.data.twilio.from_numbers?.length > 0) {
              setValue("from_number", response.data.twilio.from_numbers[0]);
            }
          }
        }
      } catch (error) {
        console.error("Failed to fetch config:", error);
      }
    };

    fetchConfig();
  }, [setValue, getAccessToken, authLoading, user]);

  // Load test phone number from user config
  useEffect(() => {
    if (!userConfigLoading && userConfig?.test_phone_number) {
      setValue("test_phone_number", userConfig.test_phone_number);
    }
  }, [userConfig, userConfigLoading, setValue]);

  const onSubmit = async (data: TelephonyConfigForm) => {
    setIsLoading(true);

    try {
      const accessToken = await getAccessToken();

      const requestBody: TwilioConfigurationRequest = {
        provider: "twilio",
        from_numbers: [data.from_number],
        account_sid: data.account_sid ?? "",
        auth_token: data.auth_token ?? "",
      };

      const response = await saveTelephonyConfigurationApiV1OrganizationsTelephonyConfigPost({
        headers: { Authorization: `Bearer ${accessToken}` },
        body: requestBody,
      });

      if (response.error) {
        const errorMsg = typeof response.error === 'string'
          ? response.error
          : (response.error as { detail?: string })?.detail || "Failed to save configuration";
        throw new Error(errorMsg);
      }

      // Save test phone number to user config if provided
      if (data.test_phone_number && userConfig) {
        await saveUserConfig({ ...userConfig, test_phone_number: data.test_phone_number });
      }

      toast.success("Telephony configuration saved successfully");
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "Failed to save configuration"
      );
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="container mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-3xl font-bold mb-2">Configure Telephony</h1>
        <p className="text-muted-foreground">
          Set up your telephony provider to make phone calls
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Setup Guide - Left Side */}
        <div className="space-y-4">
          <Card className="border-0 bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white overflow-hidden">
            <CardHeader className="pb-4">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-red-500/20 text-red-400">
                  <Phone className="h-5 w-5" />
                </div>
                <div>
                  <CardTitle className="text-xl text-white">
                    Twilio Setup Guide
                  </CardTitle>
                  <CardDescription className="text-slate-400">
                    Follow these steps to connect your account
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              {/* Twilio Instructions */}
              <div className="space-y-4">
                  <div className="flex gap-4">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-red-500/20 text-red-400 flex items-center justify-center font-semibold text-sm">1</div>
                    <div>
                      <h4 className="font-medium text-white mb-1">Create a Twilio Account</h4>
                      <p className="text-sm text-slate-400">
                        Sign up at{" "}
                        <a href="https://www.twilio.com/try-twilio" target="_blank" rel="noopener noreferrer" className="text-red-400 hover:text-red-300 inline-flex items-center gap-1">
                          twilio.com <ExternalLink className="h-3 w-3" />
                        </a>
                      </p>
                    </div>
                  </div>
                  
                  <div className="flex gap-4">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-red-500/20 text-red-400 flex items-center justify-center font-semibold text-sm">2</div>
                    <div>
                      <h4 className="font-medium text-white mb-1">Get Your Credentials</h4>
                      <p className="text-sm text-slate-400">Find your <span className="text-red-400 font-mono">Account SID</span> and <span className="text-red-400 font-mono">Auth Token</span> on the Twilio Console dashboard</p>
                    </div>
                  </div>
                  
                  <div className="flex gap-4">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-red-500/20 text-red-400 flex items-center justify-center font-semibold text-sm">3</div>
                    <div>
                      <h4 className="font-medium text-white mb-1">Purchase a Phone Number</h4>
                      <p className="text-sm text-slate-400">Go to <span className="text-slate-300">Phone Numbers → Buy a Number</span> and select a number with voice capability</p>
                    </div>
                  </div>
                  
                  <div className="flex gap-4">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-red-500/20 text-red-400 flex items-center justify-center font-semibold text-sm">4</div>
                    <div>
                      <h4 className="font-medium text-white mb-1">Enter Details Here</h4>
                      <p className="text-sm text-slate-400">Paste your credentials in the form and save</p>
                    </div>
                  </div>

                  <div className="mt-6 p-4 rounded-xl bg-slate-800/50 border border-slate-700/50">
                    <div className="flex items-start gap-3">
                      <Key className="h-5 w-5 text-amber-400 mt-0.5 flex-shrink-0" />
                      <div>
                        <h5 className="font-medium text-amber-400 text-sm">Where to find credentials</h5>
                        <p className="text-xs text-slate-400 mt-1">
                          Console → Account → Keys & Credentials → API Keys
                        </p>
                      </div>
                    </div>
                  </div>
                </div>

            </CardContent>
          </Card>

          {/* Quick Tips Card */}
          <Card className="border border-slate-800 bg-slate-900/50">
            <CardContent className="pt-5">
              <div className="flex items-start gap-3">
                <CheckCircle2 className="h-5 w-5 text-green-400 mt-0.5 flex-shrink-0" />
                <div>
                  <h5 className="font-medium text-slate-200 text-sm">Ready to test?</h5>
                  <p className="text-xs text-slate-400 mt-1">
                    After saving, go to your workflow and click &quot;Test Call&quot; to verify your configuration works correctly.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Configuration Form - Right Side */}
        <div>
            <form onSubmit={handleSubmit(onSubmit)}>
              <Card>
                <CardHeader>
                  <CardTitle>Provider Configuration</CardTitle>
                  <CardDescription>
                    Configure your telephony provider settings
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <p className="text-sm text-muted-foreground">
                    Twilio is the only available telephony provider.
                  </p>

                  {/* Twilio-specific fields */}
                  <>
                      <div className="space-y-2">
                        <Label htmlFor="account_sid">Account SID</Label>
                        <Input
                          id="account_sid"
                          autoComplete="username"
                          placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                          {...register("account_sid", {
                            required: "Account SID is required",
                          })}
                        />
                        {errors.account_sid && (
                          <p className="text-sm text-red-500">
                            {errors.account_sid.message}
                          </p>
                        )}
                      </div>

                      <div className="space-y-2">
                        <Label htmlFor="auth_token">Auth Token</Label>
                        <Input
                          id="auth_token"
                          type="password"
                          autoComplete="current-password"
                          placeholder={
                            hasExistingConfig
                              ? "Leave masked to keep existing"
                              : "Enter your auth token"
                          }
                          {...register("auth_token", {
                            required: !hasExistingConfig
                              ? "Auth token is required"
                              : false,
                          })}
                        />
                        {errors.auth_token && (
                          <p className="text-sm text-red-500">
                            {errors.auth_token.message}
                          </p>
                        )}
                      </div>

                      <div className="space-y-2">
                        <Label htmlFor="from_number">From Phone Number</Label>
                        <Input
                          id="from_number"
                          autoComplete="tel"
                          placeholder="+1234567890"
                          {...register("from_number", {
                            required: "Phone number is required",
                            pattern: {
                              value: /^\+[1-9]\d{1,14}$/,
                              message:
                                "Enter a valid phone number with country code (e.g., +1234567890)",
                            },
                          })}
                        />
                        {errors.from_number && (
                          <p className="text-sm text-red-500">
                            {errors.from_number.message}
                          </p>
                        )}
                      </div>
                    </>

                  {/* Test Phone Number - Common field for all providers */}
                  <div className="pt-4 border-t border-slate-800">
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <UserRound className="h-4 w-4 text-slate-400" />
                        <Label htmlFor="test_phone_number">Your Phone Number (for testing)</Label>
                      </div>
                      <Input
                        id="test_phone_number"
                        autoComplete="tel"
                        placeholder="+919876543210"
                        {...register("test_phone_number", {
                          pattern: {
                            value: /^\+[1-9]\d{1,14}$/,
                            message:
                              "Enter a valid phone number with country code (e.g., +919876543210)",
                          },
                        })}
                      />
                      <p className="text-xs text-slate-400">
                        This number will be pre-filled when making test calls. The agent will call this number.
                      </p>
                      {errors.test_phone_number && (
                        <p className="text-sm text-red-500">
                          {errors.test_phone_number.message}
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="pt-4">
                    <Button
                      type="submit"
                      className="w-full"
                      disabled={isLoading}
                    >
                      {isLoading ? "Saving..." : "Save Configuration"}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </form>
          </div>

      </div>
    </div>
  );
}
