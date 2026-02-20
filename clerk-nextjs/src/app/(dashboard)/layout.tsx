"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserButton } from "@clerk/nextjs";
import { Toaster } from "sonner";

const navLinks = [
  { href: "/dashboard", label: "대시보드" },
  { href: "/trading", label: "트레이딩" },
  { href: "/orders", label: "주문내역" },
  { href: "/agents", label: "AI 에이전트" },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-sm">
        <div className="mx-auto flex h-14 items-center justify-between px-4 sm:px-6">
          {/* Logo + Nav */}
          <div className="flex items-center gap-6">
            <Link
              href="/dashboard"
              className="flex items-center gap-2 text-sm font-bold text-foreground"
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
                OP
              </span>
              <span className="hidden sm:inline">AI 트레이딩 코치</span>
            </Link>

            <nav className="flex items-center gap-1">
              {navLinks.map((link) => {
                const isActive = pathname === link.href;
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                      isActive
                        ? "bg-muted text-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    }`}
                  >
                    {link.label}
                  </Link>
                );
              })}
            </nav>
          </div>

          {/* User Button */}
          <div className="flex items-center">
            <UserButton
              afterSignOutUrl="/"
              appearance={{
                elements: {
                  avatarBox: "h-8 w-8",
                },
              }}
            />
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main
        className={
          pathname === "/trading"
            ? "px-2 py-2 sm:px-3"
            : "mx-auto max-w-7xl px-4 py-6 sm:px-6"
        }
      >
        {children}
      </main>

      <Toaster theme="dark" position="top-right" richColors closeButton />
    </div>
  );
}
