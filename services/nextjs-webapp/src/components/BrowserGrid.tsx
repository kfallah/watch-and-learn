"use client";

import React from "react";
import { useMJPEGVideoStream } from "@/hooks/useMJPEGVideoStream";

/**
 * Worker status from orchestrator
 */
export interface WorkerInfo {
  worker_id: number;
  status: "idle" | "running" | "error" | "starting" | "stopping";
  assigned_company: string | null;
  ports: {
    agent: number;
    video: number;
  };
}

/**
 * Single browser tile in the grid
 */
interface BrowserTileProps {
  worker: WorkerInfo;
  videoPort: number;
}

function BrowserTile({ worker, videoPort }: BrowserTileProps) {
  const videoWsUrl = `ws://localhost:${videoPort}`;

  const { videoRef, isConnected, error, reconnect } = useMJPEGVideoStream({
    url: videoWsUrl,
    onConnectionChange: () => {},
  });

  // Status badge colors
  const statusColors: Record<string, string> = {
    idle: "bg-gray-500",
    running: "bg-green-500 animate-pulse",
    error: "bg-red-500",
    starting: "bg-yellow-500",
    stopping: "bg-orange-500",
  };

  const statusBadgeColor = statusColors[worker.status] || "bg-gray-500";

  return (
    <div className="relative border border-gray-700 rounded-lg overflow-hidden bg-black h-full">
      {/* Status Badge - Top Left */}
      <div className="absolute top-2 left-2 z-10 flex items-center gap-2">
        <div className={`w-2 h-2 rounded-full ${statusBadgeColor}`}></div>
        <span className="text-xs text-white bg-black/70 px-2 py-0.5 rounded">
          Worker {worker.worker_id}
        </span>
      </div>

      {/* Company Name Badge - Top Right */}
      {worker.assigned_company && (
        <div className="absolute top-2 right-2 z-10">
          <span className="text-xs font-medium text-white bg-blue-600/90 px-2 py-0.5 rounded">
            {worker.assigned_company}
          </span>
        </div>
      )}

      {/* Video Stream */}
      <div className="w-full h-full">
        <img
          ref={videoRef}
          className="w-full h-full object-contain bg-black"
          alt={`Browser ${worker.worker_id}`}
        />

        {/* Connecting overlay */}
        {!isConnected && !error && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900/80">
            <div className="text-center">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-white mx-auto mb-2" />
              <p className="text-xs text-gray-400">Connecting...</p>
            </div>
          </div>
        )}

        {/* Error overlay */}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900/80">
            <div className="text-center">
              <p className="text-xs text-red-400 mb-2">Disconnected</p>
              <button
                onClick={reconnect}
                className="px-2 py-1 bg-blue-600 hover:bg-blue-700 rounded text-xs"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        {/* Idle placeholder */}
        {worker.status === "idle" && isConnected && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900/50 pointer-events-none">
            <span className="text-sm text-gray-400">Idle</span>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Props for the BrowserGrid component
 */
interface BrowserGridProps {
  workers: WorkerInfo[];
  activeCount?: number;
}

/**
 * BrowserGrid - Displays multiple browser video streams in a responsive grid
 *
 * The grid automatically adjusts based on the number of active workers:
 * - 1 worker: Full width
 * - 2 workers: 2 columns
 * - 3-4 workers: 2x2 grid
 * - 5-6 workers: 3x2 grid
 */
export default function BrowserGrid({ workers, activeCount }: BrowserGridProps) {
  // Base video port from environment
  const baseVideoPort = parseInt(
    process.env.NEXT_PUBLIC_VIDEO_BASE_PORT || "8766"
  );

  // Filter to only show workers that should be visible
  const visibleWorkers = activeCount
    ? workers.slice(0, activeCount)
    : workers.filter((w) => w.status !== "idle" || workers.length <= 6);

  // Determine grid columns based on worker count
  const getGridClass = (count: number) => {
    if (count <= 1) return "grid-cols-1";
    if (count <= 2) return "grid-cols-2";
    if (count <= 4) return "grid-cols-2";
    return "grid-cols-3";
  };

  const gridClass = getGridClass(visibleWorkers.length);

  return (
    <div className="w-full h-full flex flex-col">
      {/* Grid Header */}
      <div className="flex items-center justify-between px-2 py-1 bg-gray-800 border-b border-gray-700">
        <span className="text-xs text-gray-400">
          Browser Swarm ({visibleWorkers.length} active)
        </span>
        <div className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-green-500"></div>
            Running
          </span>
          <span className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-gray-500"></div>
            Idle
          </span>
          <span className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-red-500"></div>
            Error
          </span>
        </div>
      </div>

      {/* Browser Grid */}
      <div className={`flex-1 grid ${gridClass} gap-2 p-2 bg-gray-900`}>
        {visibleWorkers.map((worker) => (
          <BrowserTile
            key={worker.worker_id}
            worker={worker}
            videoPort={baseVideoPort + worker.worker_id - 1}
          />
        ))}
      </div>

      {/* Empty State */}
      {visibleWorkers.length === 0 && (
        <div className="flex-1 flex items-center justify-center text-gray-500">
          <p>No active workers. Send a command to start research.</p>
        </div>
      )}
    </div>
  );
}
