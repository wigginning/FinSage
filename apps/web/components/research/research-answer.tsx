"use client";

/**
 * ResearchAnswer（m10 T1008 / §26.10）。
 * 研究结果主组件：答案正文（citations 渲染为可点击的 CitationMarker）、warnings、claims、
 * evidences（EvidenceCard）与 calculations（CalculationCard）。
 */
import type { ReactNode } from "react";
import type { ResearchAnswerViewModel } from "@/lib/api/types";
import { FileSearch, MessageSquare, Scale, Sigma, ShieldAlert, ShieldCheck } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StateView } from "@/components/ui/state-view";
import { CitationMarker } from "./citation-marker";
import { EvidenceCard } from "./evidence-card";
import { CalculationCard } from "./calculation-card";
import { ConfidenceGauge } from "./score-bar";

/** 诚实降级阈值：低于此置信度视为"证据不足/已弃权"，用中性灰呈现而非错误红。 */
const LOW_CONFIDENCE = 0.4;

export interface ResearchAnswerProps {
  answer: ResearchAnswerViewModel;
  onSelect: (kind: "evidence" | "calculation", targetId: string) => void;
  selectedEvidenceId?: string | null;
  selectedCalculationId?: string | null;
}

function escapeRegex(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 把答案正文里的引用 marker 原位替换为可点击的 CitationMarker。 */
function renderWithCitations(
  body: string,
  answer: ResearchAnswerViewModel,
  onSelect: (evidenceId: string) => void,
): ReactNode[] {
  const citations = answer.citations.filter((c) => c.marker);
  if (citations.length === 0) {
    return renderMarkdown(body);
  }
  const byMarker = new Map(citations.map((c) => [c.marker, c]));
  const markers = [...byMarker.keys()].sort((a, b) => b.length - a.length);
  const pattern = new RegExp(`(${markers.map(escapeRegex).join("|")})`, "g");
  const parts = body.split(pattern);
  return parts.map((part, idx) => {
    const citation = byMarker.get(part);
    if (!citation) return <span key={idx}>{renderMarkdown(part)}</span>;
    return (
      <CitationMarker
        key={idx}
        marker={citation.marker}
        evidenceId={citation.evidenceId}
        onClick={onSelect}
      />
    );
  });
}

/** 轻量安全 Markdown 渲染（P2：`**加粗**` 等此前以原始符号显示，审计 §2.8）。
 *
 * 只渲染内联加粗/斜体/行内代码/换行，全部转为 React 节点 —— 绝不使用
 * dangerouslySetInnerHTML，外部文档/LLM 输出是不可信输入（AGENTS.md §7）。
 */
function renderMarkdown(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const lines = text.split(/\r?\n/);
  lines.forEach((line, li) => {
    if (li > 0) nodes.push(<br key={`br-${li}`} />);
    // 行内代码 `code`
    const codeParts = line.split(/(`[^`]+`)/g);
    codeParts.forEach((seg, si) => {
      if (seg.startsWith("`") && seg.endsWith("`") && seg.length > 1) {
        nodes.push(
          <code
            key={`${li}-${si}`}
            className="rounded bg-muted px-1 py-0.5 font-mono text-xs"
          >
            {seg.slice(1, -1)}
          </code>,
        );
      } else {
        nodes.push(...renderInline(seg, `${li}-${si}`));
      }
    });
  });
  return nodes;
}

/** 内联加粗/斜体。 */
function renderInline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  // 交替匹配 **bold** 与 *italic*（先 bold，避免被 * 吞并）。
  const re = /(\*\*[^*]+\*\*|\*[^*\n]+\*)/g;
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  let idx = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > lastIndex) {
      out.push(<span key={`${keyBase}-t${idx++}`}>{text.slice(lastIndex, m.index)}</span>);
    }
    const token = m[0];
    if (token.startsWith("**") && token.endsWith("**") && token.length > 4) {
      out.push(<strong key={`${keyBase}-b${idx++}`}>{token.slice(2, -2)}</strong>);
    } else if (token.length > 2) {
      out.push(<em key={`${keyBase}-i${idx++}`}>{token.slice(1, -1)}</em>);
    } else {
      out.push(<span key={`${keyBase}-t${idx++}`}>{token}</span>);
    }
    lastIndex = m.index + token.length;
  }
  if (lastIndex < text.length) {
    out.push(<span key={`${keyBase}-t${idx++}`}>{text.slice(lastIndex)}</span>);
  }
  return out.length ? out : [<span key={keyBase}>{text}</span>];
}

export function ResearchAnswer({
  answer,
  onSelect,
  selectedEvidenceId = null,
  selectedCalculationId = null,
}: ResearchAnswerProps) {
  return (
    <div className="space-y-6">
      {/* 答案正文 */}
      <Card className="border-l-2 border-l-gold-500">
        <CardHeader>
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-gold-600" aria-hidden="true" />
            <CardTitle>研究结论</CardTitle>
            <span className="ml-auto">
              <ConfidenceGauge value={answer.confidence} />
            </span>
          </div>
        </CardHeader>
        <CardContent>
          <div className="whitespace-pre-wrap text-sm leading-7 text-foreground/90">
            {renderWithCitations(answer.answer, answer, (evidenceId) => onSelect("evidence", evidenceId))}
          </div>
        {/* ADR-0018：多空分歧度 / 证据情绪聚合。
            两者均由后端确定性算出，此前从未下发到前端；为 null 时不渲染任何占位（ADR-0005）。 */}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {answer.disagreement !== null && Number.isFinite(answer.disagreement) ? (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs text-muted-foreground"
              title="多空双方论据集的分歧程度（Jaccard 距离，确定性计算）"
              data-testid="disagreement-badge"
            >
              <Scale className="h-3.5 w-3.5" aria-hidden="true" />
              多空分歧度 {(answer.disagreement * 100).toFixed(0)}%
            </span>
          ) : null}
          {answer.sentimentSummary && answer.sentimentSummary.analyzed > 0 ? (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs text-muted-foreground"
              title={`规则法关键词打分（${answer.sentimentSummary.method}），未经实测校准`}
              data-testid="sentiment-badge"
            >
              证据情绪 · 正面 {answer.sentimentSummary.positive} / 中性{" "}
              {answer.sentimentSummary.neutral} / 负面 {answer.sentimentSummary.negative}
              {/* 诚实标注：规则法未校准（ADR-0011），不得冒充权威情绪结论。 */}
              <em className="not-italic text-muted-foreground/70">（未校准）</em>
            </span>
          ) : null}
        </div>
        </CardContent>
      </Card>

      {/* 诚实降级（§3.2）：低置信度/证据不足用中性灰呈现，区别于"错误/加载失败"的红 */}
      {answer.confidence < LOW_CONFIDENCE ? (
        <Card className="bg-muted/40" aria-label="证据不足">
          <CardContent className="p-4">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
              <ShieldCheck className="h-4 w-4" aria-hidden="true" />
              证据不足 · 低置信度
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              系统对本次结论的证据支持不足，置信度较低。这是 FinSage 的诚实边界——宁可弃权也不编造数据。
              建议补充更多来源、调整问题表述后重试。
            </p>
          </CardContent>
        </Card>
      ) : null}

      {/* warnings */}
      {answer.warnings.length > 0 ? (
        <Alert
          variant="warning"
          title={
            <span className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4" aria-hidden="true" />
              审计提示
            </span>
          }
        >
          <ul className="mt-2 space-y-1 text-sm text-foreground">
            {answer.warnings.map((w) => (
              <li key={w.code}>
                <span className="font-mono text-xs text-state-warning">{w.code}</span> {w.message}
              </li>
            ))}
          </ul>
        </Alert>
      ) : null}

      {/* claims */}
      {answer.claims.length > 0 ? (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <CardTitle>关键论断</CardTitle>
              <span className="ml-auto text-xs font-normal text-muted-foreground">
                {answer.claims.length} 条
              </span>
            </div>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {answer.claims.map((claim) => (
                <li
                  key={claim.id}
                  className="flex items-start gap-2 rounded-md p-2 text-sm hover:bg-muted/60"
                >
                  <span
                    className={
                      claim.verified
                        ? "mt-1.5 h-2 w-2 shrink-0 rounded-full bg-state-success"
                        : "mt-1.5 h-2 w-2 shrink-0 rounded-full bg-state-warning"
                    }
                    aria-hidden="true"
                  />
                  <span className="flex-1">
                    {claim.text}
                    <span className="tabular ml-2 text-xs text-muted-foreground">
                      {claim.claimType} · 置信 {(claim.confidence * 100).toFixed(0)}%
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      {/* evidences */}
      <section className="space-y-3">
        <h3 className="text-base font-semibold">
          证据 <span className="text-xs font-normal text-muted-foreground">({answer.evidences.length})</span>
        </h3>
        {answer.evidences.length === 0 ? (
          <StateView
            icon={FileSearch}
            title="证据不足"
            description="本次研究未检索到可引用的来源，系统已据此降低置信度，而非编造数据。"
          />
        ) : (
          answer.evidences.map((evidence) => (
            <EvidenceCard
              key={evidence.id}
              evidence={evidence}
              selected={selectedEvidenceId === evidence.id}
              onSelect={() => onSelect("evidence", evidence.id)}
            />
          ))
        )}
      </section>

      {/* calculations */}
      <section className="space-y-3">
        <h3 className="text-base font-semibold">
          财务计算{" "}
          <span className="text-xs font-normal text-muted-foreground">({answer.calculations.length})</span>
        </h3>
        {answer.calculations.length === 0 ? (
          <StateView
            icon={Sigma}
            title="暂无财务计算"
            description="本次研究未产生可复现的财务计算。"
          />
        ) : (
          answer.calculations.map((calc) => (
            <CalculationCard
              key={calc.id}
              calc={calc}
              selected={selectedCalculationId === calc.id}
              onSelect={() => onSelect("calculation", calc.id)}
            />
          ))
        )}
      </section>
    </div>
  );
}