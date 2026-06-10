// Live video player: WebRTC via go2rtc WebSocket signaling, hls.js fallback.
import Hls from 'hls.js';
import { RefreshCw, VideoOff } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Spinner } from '@/components/ui';

type PlayerState = 'connecting' | 'playing' | 'error';
type Mode = 'webrtc' | 'hls';

interface VideoPlayerProps {
  /** go2rtc stream name, e.g. "cam1" or "cam1_sub" */
  src: string;
  muted?: boolean;
  className?: string;
  /** show codec/transport corner badge */
  showStats?: boolean;
}

const WEBRTC_TIMEOUT_MS = 10_000;
const AUTO_RETRY_MS = 8000;

function go2rtcWsUrl(src: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/go2rtc/api/ws?src=${encodeURIComponent(src)}`;
}

function go2rtcHlsUrl(src: string): string {
  return `/go2rtc/api/stream.m3u8?src=${encodeURIComponent(src)}&mp4`;
}

export default function VideoPlayer({
  src,
  muted = true,
  className = '',
  showStats = false,
}: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<PlayerState>('connecting');
  const [mode, setMode] = useState<Mode>('webrtc');
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => {
    setMode('webrtc');
    setState('connecting');
    setAttempt((n) => n + 1);
  }, []);

  // --- WebRTC via go2rtc WS signaling ---
  useEffect(() => {
    if (mode !== 'webrtc') return;
    const video = videoRef.current;
    if (!video) return;

    let disposed = false;
    let pc: RTCPeerConnection | null = null;
    let ws: WebSocket | null = null;

    const fail = () => {
      if (disposed) return;
      disposed = true;
      cleanup();
      // fall back to LL-HLS before declaring failure
      setMode('hls');
    };

    const cleanup = () => {
      ws?.close();
      pc?.close();
      ws = null;
      pc = null;
    };

    const timeout = setTimeout(fail, WEBRTC_TIMEOUT_MS);

    const start = async () => {
      try {
        pc = new RTCPeerConnection({
          iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
        });
        pc.addTransceiver('video', { direction: 'recvonly' });
        pc.addTransceiver('audio', { direction: 'recvonly' });

        pc.ontrack = (ev) => {
          if (disposed || !videoRef.current) return;
          if (videoRef.current.srcObject !== ev.streams[0]) {
            videoRef.current.srcObject = ev.streams[0] ?? new MediaStream([ev.track]);
          }
        };
        pc.onconnectionstatechange = () => {
          if (!pc) return;
          if (pc.connectionState === 'connected') {
            clearTimeout(timeout);
          } else if (['failed', 'disconnected', 'closed'].includes(pc.connectionState)) {
            fail();
          }
        };

        ws = new WebSocket(go2rtcWsUrl(src));
        ws.onerror = fail;
        ws.onclose = () => {
          // signaling channel may close after negotiation — only fail if not connected
          if (pc && pc.connectionState !== 'connected' && pc.connectionState !== 'connecting') {
            fail();
          }
        };
        ws.onmessage = async (e: MessageEvent<string>) => {
          if (!pc) return;
          try {
            const msg = JSON.parse(e.data) as { type: string; value: string };
            if (msg.type === 'webrtc/answer') {
              await pc.setRemoteDescription({ type: 'answer', sdp: msg.value });
            } else if (msg.type === 'webrtc/candidate') {
              await pc.addIceCandidate({ candidate: msg.value, sdpMid: '0' });
            } else if (msg.type === 'error') {
              fail();
            }
          } catch {
            /* ignore */
          }
        };

        pc.onicecandidate = (ev) => {
          if (ev.candidate && ws?.readyState === WebSocket.OPEN) {
            ws.send(
              JSON.stringify({ type: 'webrtc/candidate', value: ev.candidate.candidate }),
            );
          }
        };

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        const sendOffer = () => {
          ws?.send(JSON.stringify({ type: 'webrtc/offer', value: offer.sdp }));
        };
        if (ws.readyState === WebSocket.OPEN) sendOffer();
        else ws.onopen = sendOffer;
      } catch {
        fail();
      }
    };

    void start();

    return () => {
      disposed = true;
      clearTimeout(timeout);
      cleanup();
      if (video.srcObject) video.srcObject = null;
    };
  }, [src, mode, attempt]);

  // --- HLS fallback ---
  useEffect(() => {
    if (mode !== 'hls') return;
    const video = videoRef.current;
    if (!video) return;

    const url = go2rtcHlsUrl(src);
    let hls: Hls | null = null;

    if (Hls.isSupported()) {
      hls = new Hls({
        lowLatencyMode: true,
        liveSyncDurationCount: 1,
        maxLiveSyncPlaybackRate: 1.5,
      });
      hls.loadSource(url);
      hls.attachMedia(video);
      hls.on(Hls.Events.ERROR, (_evt, data) => {
        if (data.fatal) setState('error');
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url;
      video.onerror = () => setState('error');
    } else {
      setState('error');
      return;
    }

    return () => {
      hls?.destroy();
      video.removeAttribute('src');
      video.load();
    };
  }, [src, mode, attempt]);

  // auto-retry while in error state
  useEffect(() => {
    if (state !== 'error') return;
    const t = setTimeout(retry, AUTO_RETRY_MS);
    return () => clearTimeout(t);
  }, [state, retry]);

  return (
    <div className={`relative overflow-hidden bg-black ${className}`}>
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted={muted}
        className="h-full w-full object-contain"
        onPlaying={() => setState('playing')}
        onWaiting={() => setState((s) => (s === 'playing' ? 'connecting' : s))}
      />

      {state === 'connecting' && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/40">
          <Spinner className="h-8 w-8" />
        </div>
      )}

      {state === 'error' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/70 text-slate-300">
          <VideoOff className="h-8 w-8" aria-hidden />
          <p className="text-sm">Câmera indisponível</p>
          <button
            type="button"
            onClick={retry}
            className="inline-flex items-center gap-2 rounded-lg bg-white/10 px-3 py-1.5 text-sm text-white transition hover:bg-white/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
          >
            <RefreshCw className="h-4 w-4" aria-hidden />
            Tentar novamente
          </button>
        </div>
      )}

      {showStats && state === 'playing' && (
        <span className="absolute right-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-white/80">
          {mode === 'webrtc' ? 'WebRTC' : 'HLS'}
        </span>
      )}
    </div>
  );
}
