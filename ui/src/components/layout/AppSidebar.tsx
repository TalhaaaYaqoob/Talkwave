"use client";

import { SignOutButton, useUser } from "@clerk/nextjs";
import { ChevronUp, LogOut } from "lucide-react";
import type { Icon } from "@phosphor-icons/react";
import {
  ChartPieSlice,
  Coins,
  Crown,
  FlowArrow,
  Lock,
  Megaphone,
  Phone,
  Plugs,
  PuzzlePiece,
  ShieldCheck,
  User as UserIcon,
  UsersThree,
} from "@phosphor-icons/react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

import logoImage from "../../../public/logo.png";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { useUserConfig } from "@/context/UserConfigContext";

interface NavItem {
  title: string;
  url: string;
  icon: Icon;
  requiresPlan?: string[]; // plans that can access this (empty = all)
  locked?: boolean;
  comingSoon?: boolean;
}



// Memoized navigation items component for better performance
const NavItems = memo(function NavItems({ 
  items, 
  pathname, 
  isActive 
}: { 
  items: NavItem[]; 
  pathname: string;
  isActive: (url: string) => boolean;
}) {
  return (
    <SidebarMenu>
      {items.map((item) => (
        <SidebarMenuItem key={item.title}>
          <SidebarMenuButton
            asChild={!item.comingSoon}
            isActive={!item.comingSoon && isActive(item.url)}
            tooltip={item.comingSoon ? `${item.title} (Coming Soon)` : item.locked ? `${item.title} (Upgrade required)` : item.title}
            className={`rounded-lg hover:bg-primary/[0.06] data-[active=true]:bg-primary/[0.08] data-[active=true]:text-primary data-[active=true]:font-medium data-[active=true]:border-l-2 data-[active=true]:border-primary text-muted-foreground hover:text-foreground transition-all duration-200 ${item.locked || item.comingSoon ? "opacity-50 cursor-default" : ""}`}
          >
            {item.comingSoon ? (
              <>
                <item.icon weight="duotone" className="size-4 shrink-0" />
                <span className="truncate">{item.title}</span>
                <Badge variant="outline" className="ml-auto shrink-0 text-[9px] px-1 py-0 border-primary/40 text-primary group-data-[collapsible=icon]:hidden">Soon</Badge>
              </>
            ) : (
              <Link href={item.url} prefetch={true}>
                <item.icon weight="duotone" className="size-4" />
                <span>{item.title}</span>
                {item.locked && <Lock weight="duotone" className="size-3 ml-auto text-amber-500" />}
              </Link>
            )}
          </SidebarMenuButton>
        </SidebarMenuItem>
      ))}
    </SidebarMenu>
  );
});

export function AppSidebar() {
  const pathname = usePathname();
  const { user, isLoaded: isUserLoaded } = useUser();
  const [mounted, setMounted] = useState(false);
  const { state, setOpen } = useSidebar();
  const { subscription, user: backendUser } = useUserConfig();

  useEffect(() => {
    setMounted(true);
  }, []);

  const isActive = useCallback((url: string) => {
    if (url === "/workflow") {
      return pathname === "/workflow" || pathname.startsWith("/workflow/");
    }
    return pathname === url || pathname.startsWith(url + "/");
  }, [pathname]);

  const isWorkflowEditor = /^\/workflow\/\d+/.test(pathname);
  const isCollapsed = state === "collapsed";
  const expandedByHover = useRef(false);

  useEffect(() => {
    if (isWorkflowEditor && state === "expanded") {
      setOpen(false);
    }
  }, [isWorkflowEditor]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSidebarMouseEnter = useCallback(() => {
    if (isWorkflowEditor && state === "collapsed") {
      expandedByHover.current = true;
      setOpen(true);
    }
  }, [setOpen, state, isWorkflowEditor]);

  const handleSidebarMouseLeave = useCallback(() => {
    if (isWorkflowEditor && expandedByHover.current) {
      expandedByHover.current = false;
      setOpen(false);
    }
  }, [setOpen, isWorkflowEditor]);

  useEffect(() => {
    if (!isWorkflowEditor) return;

    const handleClickOutside = (e: MouseEvent) => {
      const sidebar = document.querySelector('[data-sidebar="sidebar"]');
      if (sidebar && !sidebar.contains(e.target as Node) && state === "expanded") {
        expandedByHover.current = false;
        setOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isWorkflowEditor, state, setOpen]);

  // Build nav items based on subscription
  const mainNavItems: NavItem[] = useMemo(() => [
    { title: "Workflows", url: "/workflow", icon: FlowArrow },
    { title: "Meeting Agent", url: "/meeting-agent", icon: UsersThree, comingSoon: true },
    { title: "Reports", url: "/reports", icon: ChartPieSlice },
    {
      title: "Campaigns",
      url: "/campaigns",
      icon: Megaphone,
      locked: subscription ? !subscription.campaigns_enabled : false,
    },
  ], [subscription]);

  const isTrial = subscription?.plan === "trial";
  const isSuperuser = Boolean(
    backendUser && "is_superuser" in backendUser && backendUser.is_superuser
  );
  const settingsNavItems: NavItem[] = useMemo(() => {
    const items: NavItem[] = [
      {
        title: "Integrations",
        url: "/integrations",
        icon: Plugs,
        locked: subscription ? isTrial : false,
      },
      {
        title: "Custom Tools",
        url: "/custom-tools",
        icon: PuzzlePiece,
        locked: subscription ? !subscription.custom_tools_enabled : false,
      },
      { title: "Telephony", url: "/telephony-configurations", icon: Phone },
      { title: "Compliance", url: "/compliance", icon: ShieldCheck },
      { title: "Usage", url: "/usage", icon: Coins },
    ];

    if (isSuperuser) {
      items.push({ title: "Superadmin", url: "/superadmin", icon: Crown });
    }

    return items;
  }, [subscription, isTrial, isSuperuser]);

  // Plan badge for sidebar
  const planBadge = subscription?.billing_enabled ? (
    <Badge
      variant="outline"
      className={`text-[10px] px-1.5 py-0 ml-auto font-mono ${
        subscription.plan === "pro"
          ? "border-purple-500/50 text-purple-400"
          : subscription.plan === "plus"
          ? "border-primary/50 text-primary"
          : subscription.plan === "solo"
          ? "border-emerald-500/50 text-emerald-400"
          : "border-gray-500/50 text-gray-400"
      }`}
    >
      {subscription.plan === "trial" ? "Free" : subscription.plan.toUpperCase()}
    </Badge>
  ) : null;

  return (
    <Sidebar
      collapsible="icon"
      className="border-r border-sidebar-border bg-sidebar relative"
      style={{ transform: 'translateZ(0)' }}
      onMouseEnter={handleSidebarMouseEnter}
      onMouseLeave={handleSidebarMouseLeave}
    >

      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/" prefetch={true} className="flex items-center justify-center w-full py-4">
                <Image src={logoImage} alt="Talkwave" className="h-20 w-auto object-contain brightness-0 invert" priority />
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel className="font-mono text-[10px] uppercase tracking-[0.25em] text-primary/50 flex items-center gap-2">
            Main
            {!isCollapsed && planBadge}
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <NavItems items={mainNavItems} pathname={pathname} isActive={isActive} />
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel className="font-mono text-[10px] uppercase tracking-[0.25em] text-primary/50">Settings</SidebarGroupLabel>
          <SidebarGroupContent>
            <NavItems items={settingsNavItems} pathname={pathname} isActive={isActive} />
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton
                  size="lg"
                  className="rounded-xl border border-sidebar-border bg-primary/[0.03] data-[state=open]:bg-primary/[0.07] data-[state=open]:text-foreground hover:bg-primary/[0.06] text-muted-foreground transition-colors"
                >
                  <Avatar className="h-8 w-8 rounded-lg">
                    <AvatarImage 
                      src={mounted && isUserLoaded && user?.imageUrl ? user.imageUrl : undefined} 
                      alt={mounted && isUserLoaded && user?.fullName ? user.fullName : "User"} 
                    />
                    <AvatarFallback className="rounded-lg bg-primary/10 text-primary">
                      {mounted && isUserLoaded && user?.firstName ? user.firstName.charAt(0) : <UserIcon weight="duotone" className="size-4" />}
                    </AvatarFallback>
                  </Avatar>
                  <div className="grid flex-1 text-left text-sm leading-tight text-foreground">
                    <span className="truncate font-semibold">
                      {!mounted || !isUserLoaded ? "Loading..." : (user?.fullName || "User")}
                    </span>
                    <span className="truncate text-xs text-muted-foreground">
                      {!mounted || !isUserLoaded ? "..." : (user?.primaryEmailAddress?.emailAddress || "Account")}
                    </span>
                  </div>
                  <ChevronUp className="ml-auto size-4" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className="w-[--radix-dropdown-menu-trigger-width] min-w-56 rounded-lg bg-popover border-border text-foreground"
                side="bottom"
                align="end"
                sideOffset={4}
              >
                <DropdownMenuItem asChild className="focus:bg-primary/[0.08] focus:text-foreground cursor-pointer">
                  <Link href="/usage" prefetch={true}>
                    <Coins weight="duotone" className="mr-2 size-4" />
                    Usage & Billing
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuSeparator className="bg-border" />
                <SignOutButton redirectUrl="/">
                  <DropdownMenuItem className="text-red-400 focus:text-red-400 focus:bg-red-500/10 cursor-pointer">
                    <LogOut className="mr-2 size-4" />
                    Sign Out
                  </DropdownMenuItem>
                </SignOutButton>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar >
  );
}
