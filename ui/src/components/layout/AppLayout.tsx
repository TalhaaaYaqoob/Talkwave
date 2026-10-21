"use client";

import { Menu } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { ReactNode } from "react";

import logoImage from "../../../public/logo.png";

import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";

import { AppSidebar } from "./AppSidebar";

interface AppLayoutProps {
  children: ReactNode;
  headerActions?: ReactNode;
  stickyTabs?: ReactNode;
}

const AppLayout: React.FC<AppLayoutProps> = ({
  children,
  headerActions,
  stickyTabs,
}) => {
  const pathname = usePathname();

  const shouldShowSidebar = pathname !== "/" &&
    !pathname.startsWith("/handler") &&
    !pathname.startsWith("/sign-in") &&
    !pathname.startsWith("/sign-up") &&
    !pathname.startsWith("/share");

  const isWorkflowEditor = /^\/workflow\/\d+/.test(pathname);

  if (!shouldShowSidebar) {
    return <>{children}</>;
  }

  return (
    <SidebarProvider defaultOpen={!isWorkflowEditor}>
      <div className="flex h-screen w-full">
        <AppSidebar />
        <SidebarInset className="flex-1 flex flex-col min-h-0 overflow-hidden">
          <header className="sticky top-0 z-50 flex h-14 items-center gap-4 border-b bg-background px-4 md:hidden">
            <SidebarTrigger className="-ml-1">
              <Menu className="h-5 w-5" />
              <span className="sr-only">Toggle menu</span>
            </SidebarTrigger>
            <Link href="/" className="flex items-center">
              <Image src={logoImage} alt="Talkwave" className="h-8 w-auto object-contain brightness-0 invert" priority />
            </Link>
          </header>

          {headerActions && (
            <header className="sticky top-14 md:top-0 z-40 w-full border-b bg-background">
              <div className="container mx-auto px-4 py-4">
                <div className="flex items-center justify-center">
                  {headerActions}
                </div>
              </div>
            </header>
          )}

          {stickyTabs && (
            <div className="sticky top-14 md:top-0 z-40 bg-background border-b border-border">
              <div className="container mx-auto px-4">
                <div className="flex items-center justify-center py-2">
                  {stickyTabs}
                </div>
              </div>
            </div>
          )}

          <main className="flex-1 overflow-y-scroll" style={{ scrollbarGutter: 'stable' }}>
            {children}
          </main>
        </SidebarInset>
      </div>
    </SidebarProvider>
  );
};

export default AppLayout;
