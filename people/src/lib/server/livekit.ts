import "server-only";
import { AccessToken, TrackSource } from "livekit-server-sdk";
import type { TokenMinter } from "./service";

/** Short-lived room tokens. Only called after the service verified membership. */
export function livekitMinter(cfg: { url: string; apiKey: string; apiSecret: string }): TokenMinter {
  return async ({ room, identity, name, canPublishVideo }) => {
    const at = new AccessToken(cfg.apiKey, cfg.apiSecret, { identity, name, ttl: "10m" });
    at.addGrant({
      room,
      roomJoin: true,
      roomCreate: false,
      roomAdmin: false,
      canSubscribe: true,
      canPublish: true,
      canPublishData: false,
      // Camera is only grantable after both participants opted in to video.
      canPublishSources: canPublishVideo ? [TrackSource.MICROPHONE, TrackSource.CAMERA] : [TrackSource.MICROPHONE],
    });
    return { token: await at.toJwt(), url: cfg.url };
  };
}
