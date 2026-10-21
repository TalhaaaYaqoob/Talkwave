"use client";

import posthog from "posthog-js";
import { PostHogProvider as PHProvider, usePostHog } from "posthog-js/react";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { useAuth } from "@/lib/auth";

const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY || "";
const POSTHOG_HOST = process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://us.i.posthog.com";

function PostHogPageView() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const ph = usePostHog();

  useEffect(() => {
    if (pathname && ph) {
      let url = window.origin + pathname;
      const search = searchParams.toString();
      if (search) url += `?${search}`;
      ph.capture("$pageview", { $current_url: url });
    }
  }, [pathname, searchParams, ph]);

  return null;
}

function PostHogIdentify() {
  const { user } = useAuth();
  const ph = usePostHog();
  const identified = useRef(false);

  useEffect(() => {
    if (ph && user && !identified.current) {
      ph.identify(user.id, {
        email: user.email,
        provider: user.provider,
        organization_id: user.selected_organization_id,
      });
      if (user.selected_organization_id) {
        ph.group("organization", String(user.selected_organization_id), {
          name: user.organization_name,
        });
      }
      identified.current = true;
    }
  }, [ph, user]);

  return null;
}

export default function PostHogProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  if (!POSTHOG_KEY) {
    return <>{children}</>;
  }

  if (typeof window !== "undefined" && !posthog.__loaded) {
    posthog.init(POSTHOG_KEY, {
      api_host: POSTHOG_HOST,
      person_profiles: "identified_only",
      capture_pageview: false,
      capture_pageleave: true,
      autocapture: true,
    });
  }

  return (
    <PHProvider client={posthog}>
      <PostHogPageView />
      <PostHogIdentify />
      {children}
    </PHProvider>
  );
}
