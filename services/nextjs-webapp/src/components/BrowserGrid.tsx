'use client'

// James code
import { useMemo } from 'react'
import { useMJPEGVideoStream } from '@/hooks/useMJPEGVideoStream'

interface BrowserGridProps {
  workerCount: number
}

function buildStreamUrls(baseUrl: string, count: number): string[] {
  try {
    const parsed = new URL(baseUrl)
    const basePort = parsed.port
      ? parseInt(parsed.port, 10)
      : parsed.protocol === 'wss:'
      ? 443
      : 80

    return Array.from({ length: count }, (_, index) => {
      const url = new URL(parsed.toString())
      url.port = String(basePort + index)
      return url.toString()
    })
  } catch {
    return Array.from({ length: count }, () => baseUrl)
  }
}

function MJPEGTile({ url, label }: { url: string; label: string }) {
  const { videoRef, isConnected, error, reconnect } = useMJPEGVideoStream({ url })

  return (
    <div className="relative w-full h-full bg-black rounded-lg overflow-hidden">
      <img
        ref={videoRef}
        className="w-full h-full object-contain bg-black"
        alt={`${label} view`}
      />

      <div className="absolute left-2 top-2 text-xs px-2 py-1 rounded bg-black/60 text-white">
        {label} {isConnected ? '✓' : '○'}
      </div>

      {!isConnected && !error && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-800/80">
          <div className="text-center">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-white mx-auto mb-2" />
            <p className="text-xs text-gray-300">Connecting...</p>
          </div>
        </div>
      )}

      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-800/80">
          <div className="text-center">
            <p className="text-xs text-red-400 mb-2">{error}</p>
            <button
              onClick={reconnect}
              className="px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-xs"
            >
              Reconnect
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function BrowserGrid({ workerCount }: BrowserGridProps) {
  const baseUrl = process.env.NEXT_PUBLIC_VIDEO_WS_URL || 'ws://localhost:8765'
  const urls = useMemo(() => buildStreamUrls(baseUrl, workerCount), [baseUrl, workerCount])
  const rowClass = workerCount > 3 ? 'grid-rows-2' : 'grid-rows-1'

  return (
    <div className={`grid grid-cols-3 ${rowClass} gap-2 w-full h-full auto-rows-fr`}>
      {urls.map((url, index) => (
        <MJPEGTile key={url} url={url} label={`Agent ${index + 1}`} />
      ))}
    </div>
  )
}
