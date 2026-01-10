"use client";

import { useEffect, useRef, useState, useCallback } from "react";

interface VNCViewerProps {
  viewOnly?: boolean;
  onConnectionChange?: (connected: boolean) => void;
}

export default function VNCViewer({
  viewOnly = false,
  onConnectionChange,
}: VNCViewerProps) {
  const vncUrl = process.env.NEXT_PUBLIC_VNC_URL || "ws://localhost:6080";
  const containerRef = useRef<HTMLDivElement | null>(null);
  const rfbRef = useRef<any>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rfbLoaded, setRfbLoaded] = useState(false);
  const RFBRef = useRef<any>(null);

  const updateConnectionState = useCallback(
    (connected: boolean) => {
      setIsConnected(connected);
      onConnectionChange?.(connected);
    },
    [onConnectionChange]
  );

  // Dynamically import RFB (browser-only)
  useEffect(() => {
    let mounted = true;

    async function loadRFB() {
      try {
        // Dynamic import to avoid SSR issues
        const rfbModule = await import("novnc-next");
        if (mounted) {
          RFBRef.current = rfbModule.default;
          setRfbLoaded(true);
        }
      } catch (e) {
        console.error("Failed to load RFB:", e);
        if (mounted) {
          setError(`Failed to load VNC library: ${e}`);
        }
      }
    }

    loadRFB();

    return () => {
      mounted = false;
    };
  }, []);

  const connect = useCallback(() => {
    if (!containerRef.current || !RFBRef.current) return;

    // Clean up existing connection
    if (rfbRef.current) {
      try {
        rfbRef.current.disconnect();
      } catch {
        // Ignore errors during cleanup
      }
      rfbRef.current = null;
    }

    setError(null);

    try {
      const RFB = RFBRef.current;
      const rfb = new RFB(containerRef.current, vncUrl, {
        credentials: { password: "" },
      });

      rfb.viewOnly = viewOnly;
      rfb.scaleViewport = true;
      rfb.resizeSession = false;

      rfb.addEventListener("connect", () => {
        updateConnectionState(true);
      });

      rfb.addEventListener("disconnect", (e: CustomEvent) => {
        updateConnectionState(false);
        if (e.detail && e.detail.clean === false) {
          setError("Connection lost unexpectedly");
        }
      });

      rfb.addEventListener("securityfailure", (e: CustomEvent) => {
        setError(`Security failure: ${e.detail?.reason || "Unknown error"}`);
      });

      rfbRef.current = rfb;
    } catch (e) {
      setError(`Failed to connect: ${e}`);
      updateConnectionState(false);
    }
  }, [vncUrl, viewOnly, updateConnectionState]);

  // Connect when RFB is loaded
  useEffect(() => {
    if (rfbLoaded) {
      connect();
    }

    return () => {
      if (rfbRef.current) {
        try {
          rfbRef.current.disconnect();
        } catch {
          // Ignore errors during cleanup
        }
        rfbRef.current = null;
      }
    };
  }, [rfbLoaded, connect]);

  return (
    <div className="relative w-full h-full">
      <div ref={containerRef} className="w-full h-full" />

      {!isConnected && !error && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-800/80">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white mx-auto mb-2" />
            <p className="text-sm text-gray-300">Connecting to browser...</p>
          </div>
        </div>
      )}

      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-800/80">
          <div className="text-center">
            <p className="text-red-400 mb-2">{error}</p>
            <button
              onClick={connect}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm"
            >
              Reconnect
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
