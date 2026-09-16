/**
 * 根布局（m10 T1003 / §26.2-26.3）。定义 <html lang="zh-CN">、全局样式注入与外壳。
 */
import type { Metadata } from "next";
import "@/styles/globals.css";
import { Providers } from "./providers";
import { ProjectShell } from "@/components/layout/project-shell";

export const metadata: Metadata = {
  title: {
    default: "FinSage — 金融研究平台",
    template: "%s · FinSage",
  },
  description: "证据优先 · 确定性金融 · 可审计研究。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        {/* 主题防闪烁：hydration 前按 localStorage/系统偏好设置 <html class="dark"> */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("finsage-theme");if(t!=="light"&&t!=="dark"){t=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";}if(t==="dark"){document.documentElement.classList.add("dark");}}catch(e){}})();`,
          }}
        />
      </head>
      <body className="min-h-screen antialiased">
        <Providers>
          <ProjectShell>{children}</ProjectShell>
        </Providers>
      </body>
    </html>
  );
}