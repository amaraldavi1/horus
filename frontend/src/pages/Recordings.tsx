import { useQuery } from '@tanstack/react-query';
import { format } from 'date-fns';
import { Download } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, apiDownload, mediaSrc, type Recording } from '@/lib/api';
import { useCameras } from '@/hooks/data';
import { useHasRole } from '@/stores/auth';
import { fmtTime } from '@/lib/format';
import Timeline from '@/components/Timeline';
import {
  btnSecondary,
  cardCls,
  EmptyBlock,
  ErrorBlock,
  inputCls,
  LoadingBlock,
  selectCls,
} from '@/components/ui';

const SPEEDS = [0.25, 0.5, 1, 1.5, 2, 4];

export default function Recordings() {
  const camerasQuery = useCameras();
  const canExport = useHasRole('operator');

  const [cameraId, setCameraId] = useState<number | null>(null);
  const [day, setDay] = useState<string>(() => format(new Date(), 'yyyy-MM-dd'));
  const [current, setCurrent] = useState<Recording | null>(null);
  const [playhead, setPlayhead] = useState<number | null>(null);
  const [speed, setSpeed] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const pendingOffsetRef = useRef<number | null>(null);

  const cameras = camerasQuery.data ?? [];
  useEffect(() => {
    if (cameraId === null && cameras.length > 0) setCameraId(cameras[0].id);
  }, [cameras, cameraId]);

  const dayStart = useMemo(() => new Date(`${day}T00:00:00`), [day]);
  const fromIso = dayStart.toISOString();
  const toIso = new Date(dayStart.getTime() + 24 * 3600 * 1000).toISOString();

  const recordingsQuery = useQuery({
    queryKey: ['recordings', cameraId, day],
    queryFn: () => api.listRecordings({ camera_id: cameraId as number, from: fromIso, to: toIso }),
    enabled: cameraId !== null,
    staleTime: 30_000,
  });

  const eventsQuery = useQuery({
    queryKey: ['recordings-events', cameraId, day],
    queryFn: async () =>
      (
        await api.listEvents({
          camera_id: cameraId as number,
          from: fromIso,
          to: toIso,
          page: 1,
          size: 500,
        })
      ).items,
    enabled: cameraId !== null,
    staleTime: 30_000,
  });

  const segments = useMemo(
    () =>
      [...(recordingsQuery.data ?? [])].sort((a, b) => a.started_at.localeCompare(b.started_at)),
    [recordingsQuery.data],
  );

  // reset playback when camera/day change
  useEffect(() => {
    setCurrent(null);
    setPlayhead(null);
  }, [cameraId, day]);

  const seek = useCallback(
    (msEpoch: number) => {
      // find segment containing the time, otherwise the next one after it
      let target: Recording | undefined;
      let offsetS = 0;
      for (const s of segments) {
        const a = new Date(s.started_at).getTime();
        const b = new Date(s.ended_at).getTime();
        if (msEpoch >= a && msEpoch <= b) {
          target = s;
          offsetS = (msEpoch - a) / 1000;
          break;
        }
        if (a > msEpoch && !target) {
          target = s;
          offsetS = 0;
          break;
        }
      }
      if (!target) return;
      setPlayhead(new Date(target.started_at).getTime() + offsetS * 1000);
      if (current?.id === target.id && videoRef.current) {
        videoRef.current.currentTime = offsetS;
        void videoRef.current.play().catch(() => undefined);
      } else {
        pendingOffsetRef.current = offsetS;
        setCurrent(target);
      }
    },
    [segments, current],
  );

  const onTimeUpdate = () => {
    const v = videoRef.current;
    if (!v || !current) return;
    setPlayhead(new Date(current.started_at).getTime() + v.currentTime * 1000);
  };

  const onEnded = () => {
    if (!current) return;
    const idx = segments.findIndex((s) => s.id === current.id);
    const next = segments[idx + 1];
    if (next) {
      pendingOffsetRef.current = 0;
      setCurrent(next);
    }
  };

  const handleExport = async () => {
    if (!current) return;
    setExporting(true);
    setExportError(null);
    try {
      await apiDownload(
        `/recordings/${current.id}/export`,
        `gravacao-cam${current.camera_id}-${fmtTime(current.started_at).replaceAll(':', '-')}.mp4`,
      );
    } catch (e) {
      setExportError(e instanceof Error ? e.message : 'Falha ao exportar.');
    } finally {
      setExporting(false);
    }
  };

  if (camerasQuery.isLoading) return <LoadingBlock />;
  if (camerasQuery.isError) {
    return (
      <ErrorBlock message="Falha ao carregar câmeras." onRetry={() => void camerasQuery.refetch()} />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-slate-900 dark:text-white">Gravações</h1>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="rec-camera">
            Câmera
          </label>
          <select
            id="rec-camera"
            className={`${selectCls} w-auto`}
            value={cameraId ?? ''}
            onChange={(e) => setCameraId(Number(e.target.value))}
          >
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="rec-date">
            Data
          </label>
          <input
            id="rec-date"
            type="date"
            className={`${inputCls} w-auto`}
            value={day}
            max={format(new Date(), 'yyyy-MM-dd')}
            onChange={(e) => setDay(e.target.value)}
          />
        </div>
      </div>

      {cameras.length === 0 ? (
        <EmptyBlock message="Nenhuma câmera cadastrada." />
      ) : (
        <>
          {/* Player */}
          <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-black">
            {current ? (
              <video
                key={current.id}
                ref={videoRef}
                src={mediaSrc(`/recordings/${current.id}/play`)}
                controls
                autoPlay
                className="h-full w-full"
                onLoadedMetadata={() => {
                  const v = videoRef.current;
                  if (v) {
                    if (pendingOffsetRef.current !== null) {
                      v.currentTime = pendingOffsetRef.current;
                      pendingOffsetRef.current = null;
                    }
                    v.playbackRate = speed;
                  }
                }}
                onTimeUpdate={onTimeUpdate}
                onEnded={onEnded}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                {segments.length > 0
                  ? 'Clique na linha do tempo para reproduzir.'
                  : 'Sem gravações neste dia.'}
              </div>
            )}
          </div>

          {/* Controls */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1" role="group" aria-label="Velocidade de reprodução">
              {SPEEDS.map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={speed === s}
                  onClick={() => {
                    setSpeed(s);
                    if (videoRef.current) videoRef.current.playbackRate = s;
                  }}
                  className={`rounded-lg px-2.5 py-1 text-xs font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ${
                    speed === s
                      ? 'bg-blue-600 text-white'
                      : 'bg-slate-200 text-slate-600 hover:bg-slate-300 dark:bg-surface-800 dark:text-slate-300 dark:hover:bg-surface-700'
                  }`}
                >
                  {s}×
                </button>
              ))}
            </div>
            {canExport && (
              <button
                type="button"
                className={`${btnSecondary} ml-auto`}
                disabled={!current || exporting}
                onClick={() => void handleExport()}
              >
                <Download className="h-4 w-4" aria-hidden />
                {exporting ? 'Exportando…' : 'Exportar trecho'}
              </button>
            )}
          </div>
          {exportError && <p className="text-sm text-red-500">{exportError}</p>}

          {/* Timeline */}
          <div className={`${cardCls} p-4`}>
            {recordingsQuery.isLoading ? (
              <LoadingBlock label="Carregando gravações…" />
            ) : recordingsQuery.isError ? (
              <ErrorBlock
                message="Falha ao carregar gravações."
                onRetry={() => void recordingsQuery.refetch()}
              />
            ) : (
              <Timeline
                dayStart={dayStart}
                segments={segments}
                events={eventsQuery.data ?? []}
                playhead={playhead}
                onSeek={seek}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
