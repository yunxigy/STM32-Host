import { AlertTriangle, Antenna, RadioTower } from 'lucide-react';
import type { RtcmRelayStatus } from './types';

interface RtcmRelayCardProps {
  status: RtcmRelayStatus | null;
}

const FRAME_STALE_MS = 4000;

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  if (value < 1024) return `${Math.round(value)} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

function formatRate(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B/s';
  if (value < 1024) return `${Math.round(value)} B/s`;
  return `${(value / 1024).toFixed(1)} KB/s`;
}

function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '--';
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h${minutes % 60}m`;
}

export function RtcmRelayCard({ status }: RtcmRelayCardProps) {
  if (!status || status.enabled === false) {
    return (
      <div className="rounded-lg border border-slate-400/10 bg-[#0a2139]/70 p-2">
        <div className="flex items-center gap-1 text-[9px] font-semibold tracking-wide text-slate-500">
          <RadioTower className="h-3 w-3" />
          <span>差分中继</span>
        </div>
        <p className="mt-1 font-mono text-[12px] text-slate-500">未启用</p>
      </div>
    );
  }

  const base = status.base ?? null;
  const baseOnline = Boolean(status.base_online && base);
  const frameAge = status.frame_age_ms ?? -1;
  const baseStalled = baseOnline && (frameAge < 0 || frameAge > FRAME_STALE_MS);
  const rovers = status.rovers ?? [];
  const types = status.message_types ?? [];
  const typeNames = status.message_type_names ?? {};
  const warning = status.warning ?? '';

  const stateLabel = !baseOnline ? '基准站离线' : baseStalled ? '基准站无差分数据' : '差分发播中';
  const tone = !baseOnline
    ? 'border-rose-400/25 bg-rose-400/10 text-rose-300'
    : baseStalled
      ? 'border-amber-400/25 bg-amber-400/10 text-amber-300'
      : 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300';
  const dot = !baseOnline ? 'bg-rose-300' : baseStalled ? 'bg-amber-300' : 'bg-emerald-300';

  return (
    <div className="min-w-0 rounded-lg border border-cyan-300/10 bg-[#0a2139]/90 p-2 shadow-[inset_0_1px_0_rgba(120,220,255,0.05)]">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1 text-[9px] font-semibold tracking-wide text-slate-500">
          <RadioTower className="h-3 w-3 shrink-0 text-cyan-300" />
          <span className="truncate">差分中继 RTCM3</span>
        </div>
        <span className={`flex shrink-0 items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px] ${tone}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
          {stateLabel}
        </span>
      </div>

      <div className="mt-1.5 flex items-center gap-1.5 font-mono text-[11px] text-slate-300">
        <Antenna className="h-3 w-3 shrink-0 text-cyan-300/70" />
        <span className="text-cyan-200/90">:{status.port_in ?? '--'}</span>
        <span className="text-slate-500">收</span>
        <span className="text-slate-600">→</span>
        <span className="text-cyan-200/90">:{status.port_out ?? '--'}</span>
        <span className="text-slate-500">发</span>
      </div>

      <div className="mt-1.5 grid grid-cols-3 gap-1 text-center">
        <div className="rounded border border-cyan-300/10 bg-[#06182d]/70 px-1 py-1">
          <p className="text-[9px] text-slate-500">码率</p>
          <p className="font-mono text-[11px] font-semibold text-cyan-200">{formatRate(status.rate_in ?? 0)}</p>
        </div>
        <div className="rounded border border-cyan-300/10 bg-[#06182d]/70 px-1 py-1">
          <p className="text-[9px] text-slate-500">帧数</p>
          <p className="font-mono text-[11px] font-semibold text-slate-200">{status.frames_total ?? 0}</p>
        </div>
        <div className="rounded border border-cyan-300/10 bg-[#06182d]/70 px-1 py-1">
          <p className="text-[9px] text-slate-500">流动站</p>
          <p className="font-mono text-[11px] font-semibold text-slate-200">{status.rover_count ?? 0}</p>
        </div>
      </div>

      {types.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {types.map((type) => (
            <span
              key={type}
              title={typeNames[String(type)] || 'RTCM3 电文'}
              className="rounded border border-cyan-300/15 bg-cyan-400/10 px-1 py-0.5 font-mono text-[10px] text-cyan-200"
            >
              {type}
            </span>
          ))}
        </div>
      )}

      {rovers.length > 0 ? (
        <ul className="mt-1.5 max-h-24 space-y-1 overflow-y-auto">
          {rovers.map((rover) => (
            <li
              key={rover.sid}
              className="flex min-w-0 items-center justify-between gap-2 rounded border border-slate-400/10 bg-[#06182d]/60 px-1.5 py-1 font-mono text-[10px]"
            >
              <span className="shrink-0 text-slate-400">#{rover.sid}</span>
              <span className="min-w-0 flex-1 truncate text-slate-300" title={rover.addr}>
                {rover.ident || rover.addr}
              </span>
              <span className="shrink-0 text-cyan-200/80">{formatBytes(rover.bytes_sent)}</span>
              {rover.dropped > 0 && (
                <span className="shrink-0 text-amber-300" title="队列拥塞丢帧数">
                  丢{rover.dropped}
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1.5 text-[10px] text-slate-500">暂无流动站接入 {status.port_out ?? ''}</p>
      )}

      {warning ? (
        <p className="mt-1.5 flex items-start gap-1 text-[10px] leading-4 text-amber-300">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          <span className="min-w-0">{warning}</span>
        </p>
      ) : baseOnline ? (
        <p className="mt-1.5 flex items-center justify-between font-mono text-[10px] text-slate-500">
          <span>运行 {formatDuration((status.updated_at_ms ?? 0) - (base?.connected_at_ms ?? 0))}</span>
          <span>{base?.mode === 'hex' ? '十六进制' : base?.mode === 'binary' ? '二进制' : '--'}</span>
        </p>
      ) : null}
    </div>
  );
}
