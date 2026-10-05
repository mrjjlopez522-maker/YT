"use client";

// Voice/video via LiveKit. The token comes from our server only after it
// verifies membership; camera publishing is granted only after both people opt
// in. Nothing is recorded or transcribed. LiveKit does not moderate media.

import { useEffect, useRef, useState } from "react";
import type { RemoteTrack, Room } from "livekit-client";
import { Mic, MicOff, PhoneOff, Video, VideoOff, EyeOff } from "lucide-react";
import { Button, Notice, cx } from "../ui";

type CallState = "idle" | "connecting" | "connected" | "reconnecting" | "disconnected" | "error";

export function CallPanel({ sessionId, format, configured, videoAllowed, myVideoOptIn, otherVideoOptIn, otherName, onToggleVideoOptIn }: {
  sessionId: string; format: "voice" | "video"; configured: boolean; videoAllowed: boolean;
  myVideoOptIn: boolean; otherVideoOptIn: boolean; otherName: string; onToggleVideoOptIn: (v: boolean) => void;
}) {
  const [state, setState] = useState<CallState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);
  const [camOn, setCamOn] = useState(false);
  const [canVideo, setCanVideo] = useState(false);
  const [remoteBlocked, setRemoteBlocked] = useState(false);
  const [otherHere, setOtherHere] = useState(false);
  const room = useRef<Room | null>(null);
  const blockedRef = useRef(false);
  const media = useRef<HTMLDivElement>(null);

  useEffect(() => () => { room.current?.disconnect(); }, []);

  // If consent is withdrawn mid-call, turn the camera off immediately.
  useEffect(() => {
    if (!videoAllowed && camOn && room.current) {
      room.current.localParticipant.setCameraEnabled(false);
      setCamOn(false);
    }
  }, [videoAllowed, camOn]);

  if (!configured) {
    return (
      <Notice title="Voice and video aren't set up on this server" tone="neutral">
        Calls need LiveKit credentials (see Setup). Nothing is simulated — use text chat for this session.
      </Notice>
    );
  }

  const attach = (track: RemoteTrack) => {
    const el = track.attach();
    el.className = track.kind === "video" ? "w-full rounded-xl bg-ink" : "hidden";
    media.current?.appendChild(el);
  };

  const join = async () => {
    setError(null);
    setState("connecting");
    try {
      const res = await fetch(`/api/sessions/${sessionId}/token`, { method: "POST" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? "Couldn't join the call.");
      const { Room, RoomEvent } = await import("livekit-client");
      const r = new Room({ adaptiveStream: true, dynacast: true });
      room.current = r;
      r.on(RoomEvent.TrackSubscribed, (track, pub) => { if (blockedRef.current) pub.setSubscribed(false); else attach(track); });
      r.on(RoomEvent.TrackUnsubscribed, (track) => track.detach().forEach((el) => el.remove()));
      r.on(RoomEvent.Reconnecting, () => setState("reconnecting"));
      r.on(RoomEvent.Reconnected, () => setState("connected"));
      r.on(RoomEvent.Disconnected, () => { setState("disconnected"); setCamOn(false); setOtherHere(false); });
      r.on(RoomEvent.ParticipantConnected, () => setOtherHere(true));
      r.on(RoomEvent.ParticipantDisconnected, () => setOtherHere(false));
      await r.connect(body.url, body.token);
      setOtherHere(r.remoteParticipants.size > 0);
      await r.localParticipant.setMicrophoneEnabled(true); // camera always starts off
      setCanVideo(!!body.canPublishVideo);
      setMuted(false);
      setState("connected");
    } catch (e) {
      setState("error");
      setError(e instanceof Error ? e.message : "Couldn't join the call.");
    }
  };

  const leave = async () => {
    await room.current?.disconnect();
    room.current = null;
    if (media.current) media.current.innerHTML = "";
    setState("idle");
  };

  const toggleMute = async () => {
    await room.current?.localParticipant.setMicrophoneEnabled(muted);
    setMuted(!muted);
  };

  const toggleCam = async () => {
    if (!room.current) return;
    try {
      await room.current.localParticipant.setCameraEnabled(!camOn);
      setCamOn(!camOn);
    } catch {
      setError("Camera isn't permitted for this call yet. Both people need to opt in, then rejoin.");
    }
  };

  /** Immediately stop receiving the other person's audio and video. */
  const stopTheirMedia = () => {
    const r = room.current;
    if (!r) return;
    for (const p of r.remoteParticipants.values())
      for (const pub of p.trackPublications.values()) pub.setSubscribed(false);
    if (media.current) media.current.innerHTML = "";
    blockedRef.current = true;
    setRemoteBlocked(true);
  };

  const inCall = state === "connected" || state === "reconnecting";
  return (
    <div className="space-y-3">
      {format === "video" && (
        <label className="flex items-start gap-3 rounded-xl bg-paper-2 p-3 text-sm">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--color-indigo)]" checked={myVideoOptIn} onChange={(e) => onToggleVideoOptIn(e.target.checked)} />
          <span>
            I&apos;m comfortable turning on video.
            <span className="block text-muted">
              {otherVideoOptIn ? `${otherName} is too.` : `${otherName} hasn't opted in yet.`} Cameras stay off until you both agree, and either of you can switch off at any time.
            </span>
          </span>
        </label>
      )}

      <div ref={media} className="space-y-2" />

      {!inCall ? (
        <Button variant="teal" onClick={join} disabled={state === "connecting"} className="w-full">
          {state === "connecting" ? "Connecting…" : state === "disconnected" || state === "error" ? "Rejoin call" : "Join voice call"}
        </Button>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onClick={toggleMute} aria-pressed={muted}>
            {muted ? <MicOff size={16} aria-hidden /> : <Mic size={16} aria-hidden />} {muted ? "Unmute" : "Mute"}
          </Button>
          {format === "video" && (
            <Button variant="secondary" size="sm" onClick={toggleCam} disabled={!canVideo || !videoAllowed} aria-pressed={camOn}
              title={!videoAllowed ? "Both people need to opt in to video" : undefined}>
              {camOn ? <VideoOff size={16} aria-hidden /> : <Video size={16} aria-hidden />} {camOn ? "Camera off" : "Camera on"}
            </Button>
          )}
          <Button variant="secondary" size="sm" onClick={stopTheirMedia} disabled={remoteBlocked}>
            <EyeOff size={16} aria-hidden /> {remoteBlocked ? "Their media stopped" : "Stop their audio/video"}
          </Button>
          <Button variant="danger" size="sm" onClick={leave}><PhoneOff size={16} aria-hidden /> Leave call</Button>
        </div>
      )}

      <p className={cx("text-xs", state === "reconnecting" || state === "disconnected" ? "text-amber-ink" : "text-muted")} role="status" aria-live="polite">
        {state === "connected" && (otherHere ? `You and ${otherName} are on the call.` : `Waiting for ${otherName} to join the call…`)}
        {state === "reconnecting" && "Connection dropped — reconnecting…"}
        {state === "disconnected" && "You've been disconnected from the call. Text chat still works. Rejoin when you're ready."}
        {state === "idle" && "Microphone only to start. Not recorded or transcribed."}
      </p>
      {canVideo && videoAllowed === false && inCall && <p className="text-xs text-muted">Video was switched off because consent changed.</p>}
      {!canVideo && videoAllowed && inCall && format === "video" && <p className="text-xs text-muted">You both opted in — leave and rejoin the call to enable cameras.</p>}
      {error && <Notice tone="rose">{error}</Notice>}
    </div>
  );
}
