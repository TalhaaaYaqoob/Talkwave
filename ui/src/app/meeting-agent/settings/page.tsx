"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function MeetingAgentSettingsPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/meeting-agent");
  }, [router]);
  return null;
}
