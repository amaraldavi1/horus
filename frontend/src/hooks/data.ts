import { useQuery } from '@tanstack/react-query';
import { useCallback, useState } from 'react';
import { api, type CameraStatus } from '@/lib/api';
import { useStatusSocket } from '@/lib/ws';

export function useCameras() {
  return useQuery({
    queryKey: ['cameras'],
    queryFn: api.listCameras,
    staleTime: 60_000,
  });
}

/** Map camera_id → latest status, fed by the /ws/status socket. */
export function useStatusMap(): Record<number, CameraStatus> {
  const [map, setMap] = useState<Record<number, CameraStatus>>({});
  const onStatus = useCallback((s: CameraStatus) => {
    setMap((m) => ({ ...m, [s.camera_id]: s }));
  }, []);
  useStatusSocket(onStatus);
  return map;
}
