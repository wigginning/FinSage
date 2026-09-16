"use client";

/**
 * 主题切换（§1.2 修复：原"假切换"只改文案，未应用 <html class="dark">）。
 * 深色由 <html class="dark"> 触发（globals.css `html.dark` 覆写 token）。
 * 偏好持久化到 localStorage；首次访问回退系统 prefers-color-scheme。
 */
import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "finsage-theme";

/** 供根布局内联脚本使用：在 hydration 前设置初始 class，避免闪烁。 */
export function applyThemeClass(theme: Theme): void {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", theme === "dark");
}

function readStoredTheme(): Theme | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "dark" || stored === "light") return stored;
  } catch {
    /* ignore storage errors */
  }
  return null;
}

function systemTheme(): Theme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function initialTheme(): Theme {
  return readStoredTheme() ?? systemTheme();
}

/**
 * 主题状态。
 *
 * **SSR 一致性（React #418 根因修复）**：服务端读不到 localStorage /
 * prefers-color-scheme，若像旧实现那样在 `useState(initialTheme)` 里直接读，
 * 服务端恒为 light、而暗色偏好用户在客户端首帧得到 dark —— 两侧输出不一致，
 * React 报 #418 并丢弃服务端 HTML。
 *
 * 故：**服务端与客户端首帧一律返回 "light"**，真实偏好在挂载后的 effect 里补齐。
 * 视觉不会闪烁：layout.tsx 的内联脚本已在 hydration 前把 `dark` class 打到 <html> 上，
 * 这里只是让 React 的状态追上已经正确的 DOM。
 *
 * `mounted` 供消费方（主题图标、"当前：深色" 文案等）在首帧渲染 SSR 一致的内容。
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  // 挂载后补齐真实偏好（仅一次）。
  useEffect(() => {
    setTheme(initialTheme());
    setMounted(true);
  }, []);

  // 应用并持久化；mounted 之前不写，避免把 SSR 的 "light" 覆盖掉已存的 "dark"。
  useEffect(() => {
    if (!mounted) return;
    applyThemeClass(theme);
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* ignore storage errors */
    }
  }, [theme, mounted]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  return { theme, toggle, mounted };
}
