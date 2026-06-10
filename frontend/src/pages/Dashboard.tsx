import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Cpu, HardDrive } from 'lucide-react';
import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { api, type HorusEvent } from '@/lib/api';
import { useEventSocket } from '@/lib/ws';
import { useCameras, useStatusMap } from '@/hooks/data';
import { fmtRelative, formatBytes, labelPt } from '@/lib/format';
import CameraStatusBadge from '@/components/CameraStatusBadge';
import { EventIcon } from '@/components/EventCard';
import { cardCls, EmptyBlock, ErrorBlock, LoadingBlock } from '@/components/ui';

function LastEventLine({ event }: { event: HorusEvent | undefined }) {
  if (!event) {
    return <p className="text-xs text-slate-400 dark:text-slate-500">Sem eventos recentes</p>;
  }
  return (
    <p className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
      <EventIcon label={event.label} type={event.type} className="h-3.5 w-3.5" />
      {labelPt(event.label, event.type)} {fmtRelative(event.started_at)}
    </p>
  );
}

export default function Dashboard() {
  const camerasQuery = useCameras();
  const statusMap = useStatusMap();
  const queryClient = useQueryClient();

  // last event per camera — fetch recent events once, update live via WS
  const lastEventsQuery = useQuery({
    queryKey: ['dashboard-last-events'],
    queryFn: async () => {
      const res = await api.listEvents({ page: 1, size: 100 });
      const byCamera: Record<number, HorusEvent> = {};
      for (const e of res.items) {
        if (!byCamera[e.camera_id]) byCamera[e.camera_id] = e;
      }
      return byCamera;
    },
    staleTime: 30_000,
  });

  useEventSocket(
    useCallback(
      (event: HorusEvent) => {
        queryClient.setQueryData<Record<number, HorusEvent>>(
          ['dashboard-last-events'],
          (old) => ({ ...(old ?? {}), [event.camera_id]: event }),
        );
      },
      [queryClient],
    ),
  );

  const hardwareQuery = useQuery({
    queryKey: ['system-hardware'],
    queryFn: api.hardware,
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
  const storageQuery = useQuery({
    queryKey: ['system-storage'],
    queryFn: api.storage,
    staleTime: 60_000,
    refetchInterval: 120_000,
  });

  if (camerasQuery.isLoading) return <LoadingBlock />;
  if (camerasQuery.isError) {
    return (
      <ErrorBlock
        message="Falha ao carregar as câmeras."
        onRetry={() => void camerasQuery.refetch()}
      />
    );
  }

  const cameras = camerasQuery.data ?? [];
  const lastEvents = lastEventsQuery.data ?? {};
  const hw = hardwareQuery.data;
  const storage = storageQuery.data;
  const usagePct =
    storage && storage.total_bytes > 0
      ? storage.usage_pct || (storage.used_bytes / storage.total_bytes) * 100
      : 0;

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-slate-900 dark:text-white">Dashboard</h1>

      {/* System tiles */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className={`${cardCls} p-4`}>
          <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
            <Cpu className="h-4 w-4 text-blue-500" aria-hidden /> Hardware
          </div>
          {hardwareQuery.isLoading && (
            <p className="text-sm text-slate-400 dark:text-slate-500">Carregando…</p>
          )}
          {hardwareQuery.isError && (
            <p className="text-sm text-slate-400 dark:text-slate-500">Indisponível</p>
          )}
          {hw && (
            <div className="space-y-1 text-sm text-slate-600 dark:text-slate-400">
              <p>
                Decodificação:{' '}
                <span className="font-medium uppercase text-slate-900 dark:text-white">
                  {hw.selected.decode}
                </span>
              </p>
              <p>
                Inferência:{' '}
                <span className="font-medium uppercase text-slate-900 dark:text-white">
                  {hw.selected.inference}
                </span>
              </p>
              {hw.gpus.length > 0 && <p className="truncate">GPU: {hw.gpus.join(', ')}</p>}
            </div>
          )}
        </div>

        <div className={`${cardCls} p-4`}>
          <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
            <HardDrive className="h-4 w-4 text-blue-500" aria-hidden /> Armazenamento
          </div>
          {storageQuery.isLoading && (
            <p className="text-sm text-slate-400 dark:text-slate-500">Carregando…</p>
          )}
          {storageQuery.isError && (
            <p className="text-sm text-slate-400 dark:text-slate-500">Indisponível</p>
          )}
          {storage && (
            <div className="space-y-2">
              <div
                className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-surface-700"
                role="progressbar"
                aria-label="Uso de armazenamento"
                aria-valuenow={Math.round(usagePct)}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <div
                  className={`h-full rounded-full ${
                    usagePct >= 90 ? 'bg-red-500' : usagePct >= 75 ? 'bg-amber-400' : 'bg-blue-500'
                  }`}
                  style={{ width: `${Math.min(100, usagePct)}%` }}
                />
              </div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {formatBytes(storage.used_bytes)} de {formatBytes(storage.total_bytes)} usados (
                {usagePct.toFixed(0)}%) · {formatBytes(storage.free_bytes)} livres
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Camera cards */}
      <div>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Câmeras ({cameras.length})
        </h2>
        {cameras.length === 0 ? (
          <EmptyBlock message="Nenhuma câmera cadastrada. Adicione uma em Câmeras." />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {cameras.map((cam) => {
              const st = statusMap[cam.id];
              return (
                <Link
                  key={cam.id}
                  to="/live"
                  className={`${cardCls} block p-4 transition hover:border-blue-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 dark:hover:border-blue-500`}
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-semibold text-slate-900 dark:text-white">
                      {cam.name}
                    </span>
                    <CameraStatusBadge status={st} />
                  </div>
                  <p className="mb-1 text-xs text-slate-500 dark:text-slate-400">
                    {st
                      ? st.state === 'online'
                        ? `${st.fps.toFixed(0)} fps · ${st.decode_path}`
                        : st.error || st.state
                      : 'Aguardando status…'}
                  </p>
                  <LastEventLine event={lastEvents[cam.id]} />
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
