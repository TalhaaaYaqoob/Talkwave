import "./globals.css";

import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";

import AppLayout from "@/components/layout/AppLayout";
import PostHogProvider from "@/components/PostHogProvider";
import { Toaster } from "@/components/ui/sonner";
import { OnboardingProvider } from "@/context/OnboardingContext";
import { UserConfigProvider } from "@/context/UserConfigContext";
import { AuthProvider } from "@/lib/auth";


const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const instrumentSerif = Instrument_Serif({
  variable: "--font-instrument-serif",
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: {
    default: "TalkWave",
    template: "%s | TalkWave",
  },
  description: "Build, test, and run AI voice agents.",
  robots: {
    index: false,
    follow: false,
  },
  icons: {
    icon: "/favicon.svg",
  },
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode
}) {

  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} ${instrumentSerif.variable} antialiased`}>
        <AuthProvider>
          <PostHogProvider>
            <UserConfigProvider>
              <OnboardingProvider>
                <AppLayout>
                  {children}
                </AppLayout>
                <Toaster />
              </OnboardingProvider>
            </UserConfigProvider>
          </PostHogProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
