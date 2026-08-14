"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, API_BASE, IndexJob, JobStage } from "./api";

/**
 * 索引进度实时订阅（M9 F1）。
 *
 * 后端 `GET /projects/{id}/progress` 是 SSE：首帧推当前快照，之后推增量，
 * 终态（succeeded/failed）推完即关流；没有运行中的任务时直接关流。
 *
 * 两个必须注意的 EventSource 行为：
 * 1. 服务端正常关流后它会**自动重连**。所以收到终态必须主动 close，
 *    否则会对着已结束的任务反复建连。
 * 2. 关流也会触发 onerror。终态之后的 onerror 是预期的，不能计入失败。
 * 连续失败超过阈值就 close 掉、回退到 2s 轮询 jobs/latest，保证进度条不会瞎。
 */

export interface IndexProgress {
  stage: JobStage | string;
  progress: number;
  status: "running" | "succeeded" | "failed" | "idle" | string;
  stats?: Record<string, number | string | boolean>;
}

/** 连续几次连接失败后放弃 SSE，回退轮询。 */
const MAX_ERRORS = 3;
const POLL_MS = 2000;

const isTerminal = (status: string): boolean =>
  status === "succeeded" || status === "failed";

function fromJob(job: IndexJob): IndexProgress {
  return {
    stage: job.stage,
    progress: job.progress,
    status: job.status,
    stats: job.stats_json,
  };
}

export interface UseIndexProgressResult {
  progress: IndexProgress | null;
  /** SSE 正连着（用于开发期排查，UI 上不一定展示）。 */
  live: boolean;
  /** 已回退到轮询——SSE 连不上时的保底模式。 */
  degraded: boolean;
}

/**
 * @param projectId 目标项目
 * @param enabled   只在需要时连（项目处于 indexing、或刚触发过索引）
 * @param onFinish  终态回调：页面据此重新拉一次项目/报告数据
 */
export function useIndexProgress(
  projectId: string | null,
  enabled: boolean,
  onFinish?: () => void
): UseIndexProgressResult {
  const [progress, setProgress] = useState<IndexProgress | null>(null);
  const [live, setLive] = useState(false);
  const [degraded, setDegraded] = useState(false);

  // onFinish 放 ref：调用方多半传内联函数，进依赖会让订阅反复重建
  const finishRef = useRef(onFinish);
  finishRef.current = onFinish;

  const finish = useCallback(() => {
    finishRef.current?.();
  }, []);

  useEffect(() => {
    if (!projectId || !enabled) {
      setLive(false);
      return;
    }

    let closed = false;
    let errors = 0;
    let source: EventSource | null = null;
    let poller: ReturnType<typeof setInterval> | null = null;
    // 终态之后服务端会关流并触发 onerror，那属于正常收尾，不能算失败
    let done = false;

    const stop = () => {
      closed = true;
      source?.close();
      source = null;
      if (poller) clearInterval(poller);
      poller = null;
      setLive(false);
    };

    const settle = (next: IndexProgress) => {
      setProgress(next);
      if (isTerminal(next.status)) {
        done = true;
        stop();
        finish();
      }
    };

    /** SSE 连不上时的保底：老老实实轮询 jobs/latest。 */
    const startPolling = () => {
      if (closed || poller) return;
      setDegraded(true);
      const tick = async () => {
        try {
          const job = await api<IndexJob>(`/projects/${projectId}/jobs/latest`);
          if (closed) return;
          settle(fromJob(job));
        } catch {
          /* 没有任务或请求失败：下一轮再试 */
        }
      };
      tick();
      poller = setInterval(tick, POLL_MS);
    };

    const connect = () => {
      if (typeof window === "undefined" || typeof EventSource === "undefined") {
        startPolling();
        return;
      }
      // API_BASE 可能是相对路径（子路径部署），EventSource 接受相对 URL；
      // withCredentials 是给本地开发的跨端口形态用的，同源时无副作用。
      const url = `${API_BASE}/projects/${projectId}/progress`;
      const es = new EventSource(url, { withCredentials: true });
      source = es;

      es.onopen = () => {
        errors = 0;
        setLive(true);
        setDegraded(false);
      };

      // 后端帧带事件名（event: progress）——onmessage 只收匿名帧，必须用
      // addEventListener 订阅具名事件，否则所有进度都被浏览器静默丢弃
      es.addEventListener("progress", (e: MessageEvent) => {
        if (closed) return;
        errors = 0;
        try {
          const data = JSON.parse(e.data) as IndexProgress;
          if (data && typeof data.status === "string") settle(data);
        } catch {
          /* 非 JSON 帧，忽略 */
        }
      });

      es.onerror = () => {
        if (closed || done) return;
        setLive(false);
        errors += 1;
        if (errors >= MAX_ERRORS) {
          // 放弃 SSE（EventSource 自己还会重连，必须显式关掉）
          es.close();
          source = null;
          startPolling();
        }
        // 未超阈值就交给 EventSource 原生重连，不做额外处理
      };
    };

    setDegraded(false);
    connect();

    return stop;
  }, [projectId, enabled, finish]);

  return { progress, live, degraded };
}
