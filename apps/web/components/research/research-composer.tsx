"use client";

/**
 * ResearchComposer（m10 T1004 / §26.10）。
 * 职责：创建 Research Task。
 * 输入 query/company/ticker/market/options；提交经 api.research.create 成功后回调 onSubmitted(task)。
 * 禁止承担：Evidence 渲染 / SSE 解析 / 财务计算。
 * 校验用 Zod（§26.1）。
 */
import { useMemo, useState } from "react";
import { z } from "zod";
import { api } from "@/lib/api/client";
import type { ResearchRequestDto, ResearchTaskViewModel } from "@/lib/api/types";
import { MARKETS } from "@/lib/constants/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Alert } from "@/components/ui/alert";
import { Switch } from "@/components/ui/switch";

const researchSchema = z.object({
  query: z.string().min(1, "请填写研究主题").max(2000, "研究主题过长"),
  company: z.string().max(200),
  ticker: z.string().max(30),
  market: z.enum(MARKETS),
});

export interface ResearchComposerProps {
  onSubmitted(task: ResearchTaskViewModel): void;
  defaultCompany?: string;
  defaultTicker?: string;
}

export function ResearchComposer({
  onSubmitted,
  defaultCompany = "",
  defaultTicker = "",
}: ResearchComposerProps) {
  const [query, setQuery] = useState("");
  const [company, setCompany] = useState(defaultCompany);
  const [ticker, setTicker] = useState(defaultTicker);
  const [market, setMarket] = useState<(typeof MARKETS)[number]>("CN");
  const [rag, setRag] = useState(true);
  const [calculation, setCalculation] = useState(true);
  const [crossValidation, setCrossValidation] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);

  const canSubmit = useMemo(() => query.trim().length > 0, [query]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const parsed = researchSchema.safeParse({ query, company, ticker, market });
    if (!parsed.success) {
      const errs: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        errs[String(issue.path[0])] = issue.message;
      }
      setFieldErrors(errs);
      return;
    }
    setFieldErrors({});
    setSubmitError(null);
    setSubmitting(true);

    // 交叉验证为系统固定行为（§16.5 governance），不入请求体；仅映射 DTO 存在的字段。
    const payload: ResearchRequestDto = {
      query: query.trim(),
      company: company.trim() || undefined,
      ticker: ticker.trim() || undefined,
      market,
      options: {
        include_evidence: rag,
        include_calculation: calculation,
        max_evidence: 10,
      },
    };

    const result = await api.research.create(payload);
    setSubmitting(false);

    if (!result.ok) {
      setSubmitError(result.error.userMessage);
      return;
    }

    const task: ResearchTaskViewModel = {
      taskId: result.data.task_id,
      sessionId: null,
      traceId: result.data.trace_id,
      status: "queued",
      progress: 0,
      query: query.trim(),
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      result: null,
      error: null,
    };
    onSubmitted(task);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-4 rounded-lg border border-border bg-card p-6"
      aria-label="研究提交表单"
    >
      <div>
        <label htmlFor="session-query" className="mb-1.5 block text-sm font-medium">
          研究主题
        </label>
        <Textarea
          id="session-query"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="例如：评估宁德时代 2024 年营收增长与毛利率变化并给出原因"
          rows={4}
          error={Boolean(fieldErrors.query)}
          aria-invalid={Boolean(fieldErrors.query)}
        />
        {fieldErrors.query ? (
          <p className="mt-1 text-xs text-state-error">{fieldErrors.query}</p>
        ) : null}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <label htmlFor="session-company" className="mb-1.5 block text-sm font-medium">
            公司
          </label>
          <Input
            id="session-company"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            placeholder="宁德时代"
          />
        </div>
        <div>
          <label htmlFor="session-ticker" className="mb-1.5 block text-sm font-medium">
            股票代码
          </label>
          <Input
            id="session-ticker"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="300750"
          />
        </div>
        <div>
          <label htmlFor="session-market" className="mb-1.5 block text-sm font-medium">
            市场
          </label>
          <Select
            id="session-market"
            value={market}
            onChange={(e) => setMarket(e.target.value as (typeof MARKETS)[number])}
          >
            {MARKETS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <fieldset className="space-y-3">
        <legend className="text-sm font-medium">研究选项</legend>
        <div className="flex flex-wrap gap-x-6 gap-y-3">
          <SwitchRow
            label="启用 RAG 检索"
            checked={rag}
            onCheckedChange={setRag}
            id="opt-rag"
          />
          <SwitchRow
            label="启用财务计算"
            checked={calculation}
            onCheckedChange={setCalculation}
            id="opt-calc"
          />
          <SwitchRow
            label="启用交叉验证（固定启用）"
            checked={crossValidation}
            onCheckedChange={setCrossValidation}
            id="opt-cross"
            disabled
          />
        </div>
      </fieldset>

      {submitError ? <Alert variant="error" description={submitError} /> : null}

      <div className="flex items-center justify-end gap-2">
        <Button type="submit" variant="primary" loading={submitting} disabled={!canSubmit || submitting}>
          提交研究
        </Button>
      </div>
    </form>
  );
}

function SwitchRow({
  label,
  checked,
  onCheckedChange,
  id,
  disabled,
}: {
  label: string;
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  id: string;
  disabled?: boolean;
}) {
  return (
    <label htmlFor={id} className="flex items-center gap-2 text-sm">
      <Switch
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
      />
      {label}
    </label>
  );
}
