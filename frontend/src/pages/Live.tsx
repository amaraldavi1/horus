import { Maximize2, X } from 'lucide-react';
import { useState } from 'react';
import { useCameras, useStatusMap } from '@/hooks/data';
import type { Camera } from '@/lib/api';
import CameraStatusBadge from '@/components/CameraStatusBadge';
import GridLayoutPicker, { useGridLayout } from '@/components/GridLayoutPicker';
import PtzControls from '@/components/PtzControls';
import VideoPlayer from '@/components/VideoPlayer';
import { EmptyBlock, ErrorBlock, LoadingBlock } from '@/components/ui';

/** go2rtc stream names per CONTRACTS §3: cam{id} (main) / cam{id}_sub (sub). */
function streamName(cam: Camera, sub: boolean): string {
  return sub && cam.sub_url ? `cam${cam.id}_sub` : `cam${cam.id}`;
}

export default function Live() {
  const camerasQuery = useCameras();
  const statusMap = useStatusMap();
  const [layout, setLayout] = useGridLayout();
  const [fullscreenCam, setFullscreenCam] = useState<Camera | null>(null);

  if (camerasQuery.isLoading) return <LoadingBlock />;
  if (camerasQuery.isError) {
    return (
      <ErrorBlock message="Falha ao carregar câmeras." onRetry={() => void camerasQuery.refetch()} />
    );
  }

  const cameras = (camerasQuery.data ?? []).filter((c) => c.enabled);
  const visible = cameras.slice(0, layout.cols * layout.rows);

  // Fullscreen single view — main stream + PTZ overlay
  if (fullscreenCam) {
    const cam = fullscreenCam;
    return (
      <div className="fixed inset-0 z-50 flex flex-col bg-black">
        <div className="flex items-center justify-between px-4 py-2">
          <div className="flex items-center gap-3">
            <span className="font-medium text-white">{cam.name}</span>
            <CameraStatusBadge status={statusMap[cam.id]} withLabel />
          </div>
          <button
            type="button"
            onClick={() => setFullscreenCam(null)}
            aria-label="Fechar visualização em tela cheia"
            className="rounded-lg p-2 text-slate-300 transition hover:bg-white/10 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
          >
            <X className="h-6 w-6" />
          </button>
        </div>
        <div className="relative min-h-0 flex-1">
          <VideoPlayer src={streamName(cam, false)} className="h-full w-full" showStats />
          <div className="absolute bottom-4 right-4">
            <PtzControls cameraId={cam.id} ptz={cam.ptz} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-slate-900 dark:text-white">Ao Vivo</h1>
        <GridLayoutPicker value={layout} onChange={setLayout} />
      </div>

      {cameras.length === 0 ? (
        <EmptyBlock message="Nenhuma câmera habilitada." />
      ) : (
        <div
          className="grid gap-2"
          style={{ gridTemplateColumns: `repeat(${layout.cols}, minmax(0, 1fr))` }}
        >
          {visible.map((cam) => (
            <div key={cam.id} className="group relative aspect-video overflow-hidden rounded-lg">
              {/* substream in grid for efficiency */}
              <VideoPlayer src={streamName(cam, true)} className="h-full w-full" />
              <div className="pointer-events-none absolute inset-x-0 top-0 flex items-center justify-between bg-gradient-to-b from-black/60 to-transparent px-2.5 py-1.5">
                <span className="truncate text-xs font-medium text-white drop-shadow">
                  {cam.name}
                </span>
                <CameraStatusBadge status={statusMap[cam.id]} />
              </div>
              <button
                type="button"
                onClick={() => setFullscreenCam(cam)}
                aria-label={`Abrir ${cam.name} em tela cheia`}
                className="absolute bottom-2 right-2 rounded-lg bg-black/50 p-2 text-white opacity-0 backdrop-blur transition focus:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 group-hover:opacity-100"
              >
                <Maximize2 className="h-4 w-4" aria-hidden />
              </button>
            </div>
          ))}
          {/* fill empty cells */}
          {Array.from({ length: Math.max(0, layout.cols * layout.rows - visible.length) }).map(
            (_, i) => (
              <div
                key={`empty-${i}`}
                className="aspect-video rounded-lg border border-dashed border-slate-300 dark:border-surface-700"
              />
            ),
          )}
        </div>
      )}
    </div>
  );
}
