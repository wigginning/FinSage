"use client";

/**
 * 登录页（ADR-0019 §6）。
 *
 * 补齐 401 闭环的最后一环：批次 5 已实现"401 → 清 token + 派发事件"，但当时没有
 * /login 路由可跳，只能 console.warn 占位。本页配合 providers 的跳转逻辑把闭环接通：
 * 会话失效 → 跳登录（带回跳地址）→ 重新登录 → 回跳原页面。
 *
 * 安全：
 * - 失败提示**不区分**"账号不存在 / 口令错误 / 未激活 / 无租户归属"——后端一律
 *   FIN-1002，前端同样只给统一文案，避免账号枚举。
 * - 回跳地址只接受站内绝对路径，拒绝 `//host`、`http://...`（防开放重定向）。
 *
 * 重构：输入框改用 Input 原子组件（统一描边/focus/错误态），错误提示改用 Alert。
 */
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";

/** 只接受站内绝对路径，杜绝开放重定向。 */
function safeRedirect(raw: string | null): string {
  if (!raw) return "/";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const redirect = safeRedirect(params.get("redirect"));

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const result = await api.auth.login({
      email,
      password,
      tenant_id: tenantId.trim() ? tenantId.trim() : null,
    });
    setSubmitting(false);
    if (!result.ok) {
      setError(result.error.userMessage || "邮箱或口令不正确，请重试。");
      return;
    }
    api.setToken(result.data.access_token);
    router.replace(redirect);
  }

  return (
    <main className="mx-auto flex w-full max-w-md flex-col justify-center gap-6 px-4 py-16">
      <div>
        <h1 className="text-xl font-semibold">登录 FinSage</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          会话已失效或尚未登录，请重新登录后继续。
        </p>
      </div>

      <Card>
        <CardContent>
          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <label className="flex flex-col gap-1.5">
              <span className="text-sm">邮箱</span>
              <Input
                type="email"
                required
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                error={Boolean(error)}
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-sm">口令</span>
              <Input
                type="password"
                required
                autoComplete="current-password"
                maxLength={256}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                error={Boolean(error)}
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-sm">
                租户 ID{" "}
                <span className="text-xs text-muted-foreground">（可选，多租户归属时填写）</span>
              </span>
              <Input
                type="text"
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                placeholder="留空则取默认归属"
              />
            </label>

            {error ? <Alert variant="error" description={error} /> : null}

            <Button type="submit" size="lg" loading={submitting} className="w-full">
              {submitting ? "登录中…" : "登录"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}

export default function LoginPage() {
  // useSearchParams 需 Suspense 包裹（App Router 要求）。
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
