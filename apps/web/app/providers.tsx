"use client";

/**
 * 全局 Providers（m10 T1001 / §26.1）。聚合 TanStack Query 等客户端上下提供者。
 * 保持轻量；zustand store 为模块单例，无需 context。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { UNAUTHORIZED_EVENT } from "@/lib/api/client";

export function Providers({ children }: { children: React.ReactNode }) {
  // 每个客户端渲染使用独立 QueryClient 实例，避免跨请求状态泄漏。
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: false },
        },
      }),
  );

  // 401 闭环（ADR-0019 §6）：会话失效 → 跳登录页并带回跳地址。
  // 批次 5 时因无 /login 路由只能 console.warn 占位，现由 app/login/page.tsx 接上。
  useEffect(() => {
    const onUnauthorized = (e: Event) => {
      const detail = (e as CustomEvent<{ traceId?: string }>).detail;
      console.warn("[auth] session expired (401)", detail?.traceId);
      // 已在登录页则不再跳转，避免"自己跳自己"。
      const current = window.location.pathname;
      if (current.startsWith("/login")) return;
      const redirect = encodeURIComponent(current + window.location.search);
      // 整页跳转（而非 router.push）：顺带清掉内存中的失效状态。
      window.location.href = `/login?redirect=${redirect}`;
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}