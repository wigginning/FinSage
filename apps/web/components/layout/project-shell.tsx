"use client";

/**
 * 项目外壳（m10 T1003 / §26.3）。对齐 finsage-ui/partials/project-shell.html：
 * 顶部 Header + 左侧 Sidebar + 主内容区。响应式：桌面/笔记本显示侧栏，窄屏折叠。
 *
 * 主题切换按钮用 `useTheme()` 返回的 `mounted` 守门：mount 前固定渲染 `Moon`，
 * 与 SSR 输出一致；mount 后切到真实图标，规避 React #418 hydration mismatch。
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Building2,
  FileText,
  History,
  LayoutDashboard,
  Moon,
  Settings,
  Sun,
} from "lucide-react";
import { ROUTES } from "@/lib/constants/api";
import { cn } from "@/lib/utils";
import { useTheme } from "@/lib/theme";
import { GlobalSearch } from "./global-search";
import { NotificationBell } from "./notification-bell";

const NAV_ITEMS = [
  { href: ROUTES.home, label: "研究工作台", icon: LayoutDashboard },
  { href: ROUTES.companies, label: "公司库", icon: Building2 },
  { href: ROUTES.documents, label: "文档库", icon: FileText },
  { href: ROUTES.history, label: "研究历史", icon: History },
] as const;

export function ProjectShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { theme, toggle, mounted } = useTheme();

  const isActive = (href: string): boolean => {
    if (href === ROUTES.home) return pathname === href;
    return pathname.startsWith(href);
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="fixed top-0 left-0 right-0 z-50 flex h-14 items-center justify-between border-b border-border bg-card px-4">
        <div className="flex items-center gap-3">
          <Link
            href={ROUTES.home}
            className="flex items-center gap-2 text-primary transition-opacity hover:opacity-90"
            aria-label="FinSage 首页"
          >
            <span className="relative flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10">
              <BarChart3 className="h-5 w-5 text-primary" aria-hidden="true" />
              {/* 金色品牌标记：权威/精算的视觉锚点 */}
              <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-gold-500 ring-2 ring-background" aria-hidden="true" />
            </span>
            <span className="text-lg font-semibold tracking-tight">FinSage</span>
          </Link>
        </div>

        <div className="mx-6 hidden flex-1 max-w-xl sm:block">
          <GlobalSearch />
        </div>

        <div className="flex items-center gap-3">
          <NotificationBell />
          <button
            type="button"
            aria-label="主题"
            onClick={toggle}
            className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            {mounted && theme === "dark" ? (
              <Sun className="h-5 w-5" aria-hidden="true" />
            ) : (
              <Moon className="h-5 w-5" aria-hidden="true" />
            )}
          </button>
          <div className="hidden items-center gap-2 border-l border-border pl-3 md:flex">
            {/* P2 诚实性：无登录/身份信息时不展示伪造头像与假邮箱（审计 §2.8）。 */}
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-medium text-primary">
              <span aria-hidden="true">?</span>
            </div>
            <span className="hidden text-sm text-muted-foreground lg:block">未登录</span>
          </div>
        </div>
      </header>

      <div className="flex min-h-screen pt-14">
        <aside className="fixed bottom-0 left-0 top-14 z-40 hidden w-60 flex-col border-r border-border bg-card md:flex">
          <nav className="flex-1 space-y-1 p-3" aria-label="主导航">
            {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
              const active = isActive(href);
              return (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    active ? "bg-muted text-foreground" : "text-foreground hover:bg-muted",
                  )}
                  aria-current={active ? "page" : undefined}
                >
                  <Icon className="h-4.5 w-4.5 text-muted-foreground" aria-hidden="true" />
                  <span>{label}</span>
                </Link>
              );
            })}
            <div className="mt-4 border-t border-border pt-4">
              <Link
                href={ROUTES.settings}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive(ROUTES.settings) ? "bg-muted text-foreground" : "text-foreground hover:bg-muted",
                )}
                aria-current={isActive(ROUTES.settings) ? "page" : undefined}
              >
                <Settings className="h-4.5 w-4.5 text-muted-foreground" aria-hidden="true" />
                <span>设置</span>
              </Link>
            </div>
          </nav>
          <div className="border-t border-border p-3">
            <div className="rounded-md bg-muted px-3 py-2">
              <p className="mb-1 text-xs text-muted-foreground">系统状态</p>
              {/* P2 诚实性：未接入真实健康检查时不伪造"所有服务正常"（审计 §2.8）。 */}
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/50" aria-hidden="true" />
                <span>健康检查未接入</span>
              </div>
            </div>
          </div>
        </aside>

        {/* P1 移动端导航：窄屏用底部 Tab 栏替代侧栏（侧栏 hidden md:flex 无替代的问题）。 */}
        <nav
          className="fixed inset-x-0 bottom-0 z-40 flex border-t border-border bg-card pb-[env(safe-area-inset-bottom)] md:hidden"
          aria-label="移动端主导航"
        >
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const active = isActive(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium transition-colors",
                  active ? "text-primary" : "text-muted-foreground hover:text-foreground",
                )}
                aria-current={active ? "page" : undefined}
              >
                <Icon className="h-5 w-5" aria-hidden="true" />
                <span>{label}</span>
              </Link>
            );
          })}
        </nav>

        <main className="min-h-[calc(100vh-3.5rem)] flex-1 pb-16 md:ml-60 md:pb-0">
          <div className="mx-auto max-w-[1440px] p-6">{children}</div>
        </main>
      </div>
    </div>
  );
}