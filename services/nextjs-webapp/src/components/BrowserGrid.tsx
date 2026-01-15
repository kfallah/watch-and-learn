'use client'

import { useMemo } from 'react'
import { useMJPEGVideoStream } from '@/hooks/useMJPEGVideoStream'
import { useVideoStreamUrls, useServices } from '@/contexts/ServiceContext'

interface BrowserGridProps {
  workerCount: number
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
  // Get video stream URLs from service discovery
  const videoUrls = useVideoStreamUrls()
  const { isLoading, error } = useServices()

  // Limit to workerCount
  const urls = useMemo(() => videoUrls.slice(0, workerCount), [videoUrls, workerCount])
  const rowClass = workerCount > 3 ? 'grid-rows-2' : 'grid-rows-1'

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-900">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white mx-auto mb-4" />
          <p className="text-gray-400">Discovering services...</p>
        </div>
      </div>
    )
  }

  if (error && urls.length === 0) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-900">
        <div className="text-center">
          <p className="text-red-400 mb-2">Service discovery failed</p>
          <p className="text-gray-500 text-sm">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className={`grid grid-cols-3 ${rowClass} gap-2 w-full h-full auto-rows-fr`}>
      {urls.map((url, index) => (
        <MJPEGTile key={`agent-${index}`} url={url} label={`Agent ${index + 1}`} />
      ))}
    </div>
  )
}
