'use client'

import { useState } from 'react'
import VideoViewer from '@/components/VideoViewer'
import VNCViewer from '@/components/VNCViewer'
import ChatWindow from '@/components/ChatWindow'

type ViewMode = 'observe' | 'control'

export default function Home() {
  const [viewMode, setViewMode] = useState<ViewMode>('control')
  const [videoConnected, setVideoConnected] = useState(false)
  const [vncConnected, setVncConnected] = useState(false)
  const [isRecording, setIsRecording] = useState(false)

  return (
    <main className="flex h-screen w-screen overflow-hidden bg-gray-900">
      {/* Browser View - Left Panel */}
      <div className="flex-1 h-full flex flex-col min-w-0">
        {/* Header with mode toggle */}
        <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700 shrink-0">
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <span className={viewMode === 'observe' ? 'text-white' : ''}>
              Video: {videoConnected ? '✓' : '○'}
            </span>
            <span className={viewMode === 'control' ? 'text-white' : ''}>
              VNC: {vncConnected ? '✓' : '○'}
            </span>
          </div>

          {/* Mode Toggle Buttons */}
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg overflow-hidden border border-gray-600">
              <button
                onClick={() => setViewMode('observe')}
                className={`px-3 py-1 text-xs transition-colors ${viewMode === 'observe'
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  }`}
              >
                Observe
              </button>
              <button
                onClick={() => setViewMode('control')}
                className={`px-3 py-1 text-xs transition-colors ${viewMode === 'control'
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  }`}
              >
                Control
              </button>
            </div>

            {/* Record Button */}
            <button
              onClick={() => setIsRecording(!isRecording)}
              className={`px-3 py-1 text-xs rounded-lg border transition-colors ${isRecording
                  ? 'bg-red-600 text-white border-red-500'
                  : 'bg-gray-700 text-gray-300 border-gray-600 hover:bg-gray-600'
                }`}
            >
              {isRecording ? '● Recording' : 'Teach'}
            </button>
          </div>
        </div>

        {/* Browser Viewer */}
        <div className="flex-1 bg-black min-h-0 flex items-center justify-center">
          <div className="w-full max-h-full aspect-video">
            {viewMode === 'observe' ? (
              <VideoViewer onConnectionChange={setVideoConnected} />
            ) : (
              <VNCViewer onConnectionChange={setVncConnected} />
            )}
          </div>
        </div>
      </div>

      {/* Chat Window - Right Panel */}
      <div className="w-[400px] h-full flex flex-col bg-gray-900 border-l border-gray-700">
        <ChatWindow isRecording={isRecording} />
      </div>
    </main>
  )
}
