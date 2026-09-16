"use client";

/**
 * 通知铃铛（§2.2）：顶栏任务状态通知。
 * 轮询最近研究任务，把进入终态（completed/failed/aborted）的任务作为通知，
 * 未读角标 + 下拉面板展示，点击跳转结果页，支持"全部已读"。
 * 已读集合持久化到 localStorage，避免刷新后重复提醒。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Bell, CheckCheck, CheckCircle2, XCircle } from "lucide-react";
import { api } from "@/lib/api/client";
import { ROUTES } from "@/lib/constants/api";
import type { TaskSummaryDto, TaskStatusDto } from "@/lib/api/types";

const POLL_MS = 15_000;
const SEEN_KEY = "finsage.notifications.seen";
const TERMINAL: TaskStatusDto[] = ["completed", "failed", "aborted"];

interface NotificationItem {
  task: TaskSummaryDto;
  kind: "completed" | "failed" | "aborted";
}

function loadSeen(): Set<string> {
  try {
    const raw = localStorage.getItem(SEEN_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as unknown;
    return new Set(Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

function saveSeen(seen: Set<string>) {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify([...seen]));
  } catch {
    /* 忽略存储失败 */
  }
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  const m = Math.floor(diff / 60_000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

const KIND_META: Record<NotificationItem["kind"], { label: string; icon: typeof CheckCircle2; className: string }> = {
  completed: { label: "已完成", icon: CheckCircle2, className: "text-state-success" },
  failed: { label: "失败", icon: XCircle, className: "text-state-error" },
  aborted: { label: "已中止", icon: AlertTriangle, className: "text-state-warning" },
};

export function NotificationBell() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [seen, setSeen] = useState<Set<string>>(loadSeen);
  const boxRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    const res = await api.tasks.list({ limit: 20 });
    if (!res.ok) return;
    const terminal = (res.data.items as TaskSummaryDto[])
      .filter((t) => TERMINAL.includes(t.status))
      .map((t) => ({ task: t, kind: t.status as NotificationItem["kind"] }))
      .sort((a, b) => b.task.created_at.localeCompare(a.task.created_at));
    setItems(terminal);
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const unread = items.filter((it) => !seen.has(it.task.task_id)).length;

  function markAllRead() {
    const next = new Set(seen);
    for (const it of items) next.add(it.task.task_id);
    setSeen(next);
    saveSeen(next);
  }

  function go(task: TaskSummaryDto) {
    const next = new Set(seen);
    next.add(task.task_id);
    setSeen(next);
    saveSeen(next);
    setOpen(false);
    router.push(ROUTES.researchResult(task.task_id));
  }

  return (
    <div ref={boxRef} className="relative">
      <button
        type="button"
        aria-label="通知"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="relative rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <Bell className="h-5 w-5" aria-hidden="true" />
        {unread > 0 && (
          <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-state-error px-1 text-[10px] font-semibold leading-none text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-11 z-50 w-80 overflow-hidden rounded-lg border border-border bg-card shadow-lg">
          <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
            <p className="text-sm font-semibold">通知</p>
            {unread > 0 && (
              <button
                type="button"
                onClick={markAllRead}
                className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                <CheckCheck className="h-3.5 w-3.5" aria-hidden="true" />
                全部已读
              </button>
            )}
          </div>
          <div className="max-h-80 overflow-y-auto">
            {items.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-muted-foreground">暂无通知</p>
            ) : (
              items.map((it) => {
                const meta = KIND_META[it.kind];
                const Icon = meta.icon;
                return (
                  <button
                    key={it.task.task_id}
                    type="button"
                    onClick={() => go(it.task)}
                    className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-muted"
                  >
                    <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${meta.className}`} aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {it.task.query || it.task.company || it.task.task_id.slice(0, 8)}
                      </span>
                      <span className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                        <span>{meta.label}</span>
                        <span aria-hidden="true">·</span>
                        <span>{relativeTime(it.task.created_at)}</span>
                      </span>
                    </span>
                    {!seen.has(it.task.task_id) && (
                      <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-gold-500" aria-label="未读" />
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
