"use client"

import Link from "next/link"

import {
  IconShieldLock,
  IconDotsVertical,
  IconDeviceDesktop,
  IconLogout,
  IconMoon,
  IconSun,
  IconNotification,
  IconPlug,
  IconUserCircle,
} from "@tabler/icons-react"

import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"
import { useRouter } from "next/navigation"
import { useTheme } from "next-themes"
import { useSession, useSignOut } from "@/hooks/auth-queries"
import { clearChatDrafts } from "@/components/chat/composer"
import { noteChosenSignOut } from "@/components/shell/session-end"
import { initials } from "@/lib/format"
import { MY_APPS } from '@/lib/nav';

export function NavUser({
  user: fallback,
}: {
  user: {
    name: string
    email: string
    avatar: string
  }
}) {
  const { isMobile } = useSidebar()
  // Whoever is signed in, once the session is known; the workspace lookup is only the placeholder before that.
  const { session } = useSession()
  const user = session ? { ...fallback, name: session.user.name, email: session.user.email } : fallback
  const router = useRouter()
  const { theme, setTheme } = useTheme()
  // Signing out drops every cached query, then the guard would send this page to /login anyway; going there directly avoids a flash.
  const signOut = useSignOut()

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              data-testid="nav-user"
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
            >
              <Avatar className="h-8 w-8 rounded-lg grayscale">
                <AvatarImage src={user.avatar} alt={user.name} />
                <AvatarFallback className="rounded-lg">{initials(user.name || user.email)}</AvatarFallback>
              </Avatar>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">{user.name}</span>
                <span className="truncate text-xs text-muted-foreground">
                  {user.email}
                </span>
              </div>
              <IconDotsVertical className="ml-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
            side={isMobile ? "bottom" : "right"}
            align="end"
            sideOffset={4}
          >
            <DropdownMenuLabel className="p-0 font-normal">
              <div className="flex items-center gap-2 px-1 py-1.5 text-left text-sm">
                <Avatar className="h-8 w-8 rounded-lg">
                  <AvatarImage src={user.avatar} alt={user.name} />
                  <AvatarFallback className="rounded-lg">{initials(user.name || user.email)}</AvatarFallback>
                </Avatar>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-medium">{user.name}</span>
                  <span className="truncate text-xs text-muted-foreground">
                    {user.email}
                  </span>
                </div>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem asChild>
                <Link href="/settings/account" data-testid="nav-account">
                  <IconUserCircle />
                  Account
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link href="/settings/account/security" data-testid="nav-security">
                  <IconShieldLock />
                  Security
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link href="/work/apps" data-testid="nav-connections">
                  <IconPlug />
                  {MY_APPS}
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link href="/settings/team/notifications">
                  <IconNotification />
                  Notifications
                </Link>
              </DropdownMenuItem>
              <DropdownMenuSub>
                <DropdownMenuSubTrigger data-testid="nav-theme" className="gap-2 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 [&_svg:not([class*='text-'])]:text-muted-foreground">
                  <IconSun />
                  Theme
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                  {/* theme is undefined until the client reads the saved choice; System is the default meanwhile. */}
                  <DropdownMenuRadioGroup value={theme ?? "system"} onValueChange={setTheme}>
                    <DropdownMenuRadioItem value="light" className="[&>svg:not([class*='text-'])]:text-muted-foreground"><IconSun />Light</DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value="dark" className="[&>svg:not([class*='text-'])]:text-muted-foreground"><IconMoon />Dark</DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value="system" className="[&>svg:not([class*='text-'])]:text-muted-foreground"><IconDeviceDesktop />System</DropdownMenuRadioItem>
                  </DropdownMenuRadioGroup>
                </DropdownMenuSubContent>
              </DropdownMenuSub>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              data-testid="sign-out"
              onSelect={async () => {
                noteChosenSignOut()
                clearChatDrafts()
                await signOut.mutateAsync()
                router.replace("/login")
              }}
            >
              <IconLogout />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
