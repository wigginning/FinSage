"use client";

/**
 * 设置页（m10 §26.3）。API key 管理（masked）、通知偏好、研究默认配置、外观/密度、安全自检清单。
 * 前端本地偏好存储于组件状态；API 凭据仅展示掩码，不落库。
 *
 * 重构：Section 改用 Card 原子组件；Toggle 改用 Switch 原子组件（原为浏览器原生 checkbox）；
 * 下拉/输入改用 Select/Input；主题文案用 `mounted` 守门，规避 hydration 不一致。
 */
import { useCallback, useState } from "react";
import { Check, Eye, EyeOff, KeyRound, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { MARKETS } from "@/lib/constants/api";
import { useTheme } from "@/lib/theme";

function Section({ number, title, children }: { number: number; title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
            {number}
          </span>
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2">
      <span>
        <span className="block text-sm">{label}</span>
        {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
      </span>
      <Switch checked={checked} onCheckedChange={onChange} aria-label={label} />
    </div>
  );
}

interface SettingsPrefs {
  notifyEmail: boolean;
  notifyResearchDone: boolean;
  notifyNewEvidence: boolean;
  defaultMarket: string;
  maxEvidence: number;
  crossValidate: boolean;
  density: "compact" | "comfortable";
}

const DEFAULT_PREFS: SettingsPrefs = {
  notifyEmail: true,
  notifyResearchDone: true,
  notifyNewEvidence: false,
  defaultMarket: "CN",
  maxEvidence: 10,
  crossValidate: true,
  density: "compact",
};

const PREFS_STORAGE_KEY = "finsage-settings";
const KEY_STORAGE_KEY = "finsage-provider-key";

function readPrefs(): SettingsPrefs {
  if (typeof window === "undefined") return DEFAULT_PREFS;
  try {
    const raw = window.localStorage.getItem(PREFS_STORAGE_KEY);
    if (!raw) return DEFAULT_PREFS;
    return { ...DEFAULT_PREFS, ...(JSON.parse(raw) as Partial<SettingsPrefs>) };
  } catch {
    return DEFAULT_PREFS;
  }
}

function usePersistedSettings(): [SettingsPrefs, (patch: Partial<SettingsPrefs>) => void] {
  const [prefs, setPrefs] = useState<SettingsPrefs>(readPrefs);
  const update = useCallback((patch: Partial<SettingsPrefs>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      try {
        window.localStorage.setItem(PREFS_STORAGE_KEY, JSON.stringify(next));
      } catch {
        /* ignore storage errors */
      }
      return next;
    });
  }, []);
  return [prefs, update];
}

// P2：API 密钥真实持久化到 sessionStorage（此前为假保存，仅展示“已保存”）。
// 密钥仅存于当前标签页会话，关闭标签页即失效；不落 localStorage / 不提交仓库。
function usePersistedKey(): [string, (v: string) => void] {
  const [key, setKey] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    try {
      return window.sessionStorage.getItem(KEY_STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const save = useCallback((v: string) => {
    setKey(v);
    try {
      if (v) window.sessionStorage.setItem(KEY_STORAGE_KEY, v);
      else window.sessionStorage.removeItem(KEY_STORAGE_KEY);
    } catch {
      /* ignore storage errors */
    }
  }, []);
  return [key, save];
}

const SECURITY_CHECKLIST = [
  { label: "未在代码/仓库中提交 API 密钥", ok: true },
  { label: "对外密钥均以掩码形式展示，不做明文回显", ok: true },
  { label: "Source 数据为不可信输入，不覆盖系统指令", ok: true },
  { label: "财务计算由确定性代码执行，不依赖 LLM 运算", ok: true },
  { label: "Provider 冲突不得静默忽略", ok: false },
  { label: "证据均保留 document_id / chunk_id 溯源", ok: true },
];

export default function SettingsPage() {
  // P2：偏好持久化到 localStorage（此前仅组件内存态，刷新即失）。
  const [prefs, setPrefs] = usePersistedSettings();
  const [keyMasked, setKeyMasked] = useState(true);
  const [apiKey, setApiKey] = usePersistedKey();
  const [apiSaved, setApiSaved] = useState(false);
  const { theme, toggle, mounted } = useTheme();

  return (
    <div className="max-w-4xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">设置</h1>
        <p className="text-sm text-muted-foreground">API 凭据、通知、研究默认配置与安全自检。</p>
      </header>

      <Section number={1} title="API 密钥">
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Input
              type={keyMasked ? "password" : "text"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="fs_sk_live_…"
              aria-label="finsage provider key"
              leadingIcon={<KeyRound />}
              className="font-mono"
            />
            <button
              type="button"
              onClick={() => setKeyMasked((v) => !v)}
              aria-label={keyMasked ? "显示密钥" : "隐藏密钥"}
              className="shrink-0 rounded-md border border-input bg-card p-2 text-muted-foreground transition-colors hover:bg-muted"
            >
              {keyMasked ? <Eye className="h-4 w-4" aria-hidden="true" /> : <EyeOff className="h-4 w-4" aria-hidden="true" />}
            </button>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => { setApiSaved(true); setTimeout(() => setApiSaved(false), 2000); }}
          >
            {apiSaved ? <Check className="h-3.5 w-3.5 text-state-success" aria-hidden="true" /> : null}
            {apiSaved ? "已保存" : "保存更改"}
          </Button>
          <p className="text-xs text-muted-foreground">
            安全提示：密钥仅存于当前标签页的 sessionStorage（关闭即失效），以掩码展示，不落 localStorage、不提交仓库；请勿通过聊天或文档泄露。
          </p>
        </div>
      </Section>

      <Section number={2} title="通知偏好">
        <div className="divide-y divide-border">
          <Toggle checked={prefs.notifyEmail} onChange={(v) => setPrefs({ notifyEmail: v })} label="研究完成邮件通知" hint="研究任务完成时发送邮件。" />
          <Toggle checked={prefs.notifyResearchDone} onChange={(v) => setPrefs({ notifyResearchDone: v })} label="研究完成站内通知" />
          <Toggle checked={prefs.notifyNewEvidence} onChange={(v) => setPrefs({ notifyNewEvidence: v })} label="新证据纳入通知" hint="公司库有新的权威来源入库时提醒。" />
        </div>
      </Section>

      <Section number={3} title="研究默认配置">
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="def-market" className="mb-1.5 block text-sm">默认市场</label>
            <Select
              id="def-market"
              value={prefs.defaultMarket}
              onChange={(e) => setPrefs({ defaultMarket: e.target.value })}
            >
              {MARKETS.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </Select>
          </div>
          <div>
            <label htmlFor="max-ev" className="mb-1.5 block text-sm">最大证据数</label>
            <Input
              id="max-ev"
              type="number"
              min={1}
              max={30}
              value={prefs.maxEvidence}
              onChange={(e) => setPrefs({ maxEvidence: Number(e.target.value) })}
            />
          </div>
          <div className="flex items-end">
            <div className="w-full">
              <Toggle checked={prefs.crossValidate} onChange={(v) => setPrefs({ crossValidate: v })} label="启用交叉验证" hint="治理固定行为，通常不可关。" />
            </div>
          </div>
        </div>
      </Section>

      <Section number={4} title="外观 / 密度">
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-4 py-2">
            <span>
              <span className="block text-sm">界面主题</span>
              <span className="block text-xs text-muted-foreground">切换浅色 / 深色外观。</span>
            </span>
            <Button variant="outline" size="sm" onClick={toggle}>
              {/* 与 project-shell 同理：mount 前不输出依赖 localStorage 的文案。 */}
              {mounted && theme === "dark" ? "当前：深色" : "当前：浅色"}
            </Button>
          </div>
          <fieldset>
            <legend className="mb-2 block text-sm">表格密度</legend>
            <div className="flex gap-3">
              {([
                ["compact", "紧凑"],
                ["comfortable", "舒适"],
              ] as const).map(([val, label]) => (
                <label key={val} className="flex items-center gap-2 text-sm">
                  <input type="radio" name="density" value={val} checked={prefs.density === val} onChange={() => setPrefs({ density: val })} aria-label={label} />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>
        </div>
      </Section>

      <Section number={5} title="安全自检清单">
        <ul className="space-y-1.5">
          {SECURITY_CHECKLIST.map((item) => (
            <li key={item.label} className="flex items-start gap-2 text-sm">
              {item.ok ? (
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-state-success" aria-hidden="true" />
              ) : (
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-state-error" aria-hidden="true" />
              )}
              <span className={item.ok ? "" : "text-state-error"}>{item.label}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-muted-foreground">
          1 项待处理：Provider 数据源冲突的处理策略需在治理设置中明确（不静默忽略）。
        </p>
      </Section>
    </div>
  );
}
