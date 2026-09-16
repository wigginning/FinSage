/**
 * 错误映射（m10 / §26.12）。后端 FIN 错误码不直接展示给用户。
 * 将 §8 ErrorBody → ApiErrorViewModel（含稳定的 userMessage）。
 */
import { FIN_CODE_TO_USER } from "@/lib/constants/api";
import type { ApiErrorViewModel, ErrorBodyDto } from "./types";

const FALLBACK_USER_MESSAGE = "操作未成功，请稍后重试。";

export function mapErrorBody(body: ErrorBodyDto): ApiErrorViewModel {
  const code = body.code ?? "FIN-6001";
  return {
    code,
    message: body.message ?? "",
    userMessage: FIN_CODE_TO_USER[code] ?? FALLBACK_USER_MESSAGE,
    traceId: body.trace_id ?? null,
    retryable: body.retryable ?? false,
  };
}

export function unknownError(err: unknown): ApiErrorViewModel {
  const isNetwork = err instanceof TypeError;
  return {
    code: isNetwork ? "NETWORK_ERROR" : "UNKNOWN",
    message: isNetwork ? "网络连接失败" : "未知错误",
    userMessage: isNetwork ? "网络连接失败，请检查网络后重试。" : FALLBACK_USER_MESSAGE,
    traceId: null,
    retryable: true,
  };
}