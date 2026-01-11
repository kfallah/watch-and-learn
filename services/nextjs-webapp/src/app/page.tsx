'use client'

import { useState, useEffect, useCallback } from 'react'
import BrowserGrid, { WorkerInfo } from '@/components/BrowserGrid'
import ChatWindow from '@/components/ChatWindow'

/**
 * Multi-Agent Browser Swarm Page
 *
 * This page displays a grid of browser instances controlled by AI agents,
 * with a chat window for sending commands to the orchestrator.
 *
 * Use this page instead of the default page.tsx for swarm mode.
 * To enable: rename this file to page.tsx (backup original first)
 */
export default function SwarmHome() {
  const [workers, setWorkers] = useState<WorkerInfo[]>([])
  const [orchestratorConnected, setOrchestratorConnected] = useState(false)
  const [viewMode, setViewMode] = useState<'grid' | 'single'>('grid')
  const [selectedWorker, setSelectedWorker] = useState<number | null>(null)

  // Get worker count from environment
  const workerCount = parseInt(process.env.NEXT_PUBLIC_WORKER_COUNT || '5')

  // Initialize workers
  useEffect(() => {
    const initialWorkers: WorkerInfo[] = []
    for (let i = 1; i <= workerCount; i++) {
      initialWorkers.push({
        worker_id: i,
        status: 'idle',
        assigned_company: null,
        ports: {
          agent: 8000 + i,
          video: 8765 + i,
        },
      })
    }
    setWorkers(initialWorkers)
  }, [workerCount])

  // Connect to orchestrator WebSocket for status updates
  const connectOrchestrator = useCallback(() => {
    const wsUrl =
      process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ||
      `ws://${typeof window !== 'undefined' ? window.location.hostname : 'localhost'}:8100/ws`

    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      setOrchestratorConnected(true)
      console.log('Connected to orchestrator')
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        // Update workers status when we receive updates
        if (data.data?.workers && Array.isArray(data.data.workers)) {
          setWorkers(data.data.workers)
        }

        // Handle task progress updates
        if (data.type === 'status' && data.data?.companies) {
          // Update assigned companies to workers
          const companies: string[] = data.data.companies
          setWorkers((prev) =>
            prev.map((w, idx) => ({
              ...w,
              status: idx < companies.length ? 'running' : w.status,
              assigned_company: companies[idx] || w.assigned_company,
            }))
          )
        }

        // Reset workers on task completion
        if (data.type === 'response') {
          setTimeout(() => {
            setWorkers((prev) =>
              prev.map((w) => ({
                ...w,
                status: 'idle',
                assigned_company: null,
              }))
            )
          }, 2000)
        }
      } catch (e) {
        console.error('Failed to parse orchestrator message:', e)
      }
    }

    ws.onclose = () => {
      setOrchestratorConnected(false)
      console.log('Disconnected from orchestrator')
      // Reconnect after delay
      setTimeout(connectOrchestrator, 3000)
    }

    ws.onerror = (error) => {
      console.error('Orchestrator WebSocket error:', error)
    }

    return ws
  }, [])

  useEffect(() => {
    const ws = connectOrchestrator()
    return () => {
      ws.close()
    }
  }, [connectOrchestrator])

  return (
    <main className="flex h-screen bg-gray-900 text-white">
      {/* Browser Grid - Left Panel */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header with mode toggle */}
        <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
          <div className="flex items-center gap-4">
            <h1 className="text-lg font-semibold">Browser Swarm</h1>
            <div className="flex items-center gap-2 text-sm">
              <div
                className={`w-2 h-2 rounded-full ${
                  orchestratorConnected ? 'bg-green-500' : 'bg-red-500'
                }`}
              ></div>
              <span className="text-gray-400">
                {orchestratorConnected ? 'Connected' : 'Disconnected'}
              </span>
            </div>
          </div>

          {/* View Mode Toggle */}
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg overflow-hidden border border-gray-600">
              <button
                onClick={() => {
                  setViewMode('grid')
                  setSelectedWorker(null)
                }}
                className={`px-3 py-1 text-xs transition-colors ${
                  viewMode === 'grid'
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                }`}
              >
                Grid View
              </button>
              <button
                onClick={() => setViewMode('single')}
                className={`px-3 py-1 text-xs transition-colors ${
                  viewMode === 'single'
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                }`}
              >
                Single View
              </button>
            </div>

            {/* Worker count badge */}
            <span className="text-xs text-gray-400 bg-gray-700 px-2 py-1 rounded">
              {workers.filter((w) => w.status === 'running').length} / {workers.length} active
            </span>
          </div>
        </div>

        {/* Browser View */}
        <div className="flex-1 min-h-0">
          {viewMode === 'grid' ? (
            <BrowserGrid workers={workers} />
          ) : (
            <div className="h-full flex">
              {/* Worker selector sidebar */}
              <div className="w-20 bg-gray-800 border-r border-gray-700 flex flex-col gap-1 p-1 overflow-y-auto">
                {workers.map((worker) => (
                  <button
                    key={worker.worker_id}
                    onClick={() => setSelectedWorker(worker.worker_id)}
                    className={`p-2 rounded text-xs text-center transition-colors ${
                      selectedWorker === worker.worker_id
                        ? 'bg-blue-600'
                        : worker.status === 'running'
                        ? 'bg-green-600/50 hover:bg-green-600'
                        : 'bg-gray-700 hover:bg-gray-600'
                    }`}
                  >
                    <div className="font-medium">W{worker.worker_id}</div>
                    <div className="text-[10px] text-gray-300 truncate">
                      {worker.assigned_company || worker.status}
                    </div>
                  </button>
                ))}
              </div>

              {/* Single worker view */}
              <div className="flex-1">
                {selectedWorker ? (
                  <BrowserGrid
                    workers={workers.filter((w) => w.worker_id === selectedWorker)}
                    activeCount={1}
                  />
                ) : (
                  <div className="h-full flex items-center justify-center text-gray-500">
                    Select a worker to view
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Chat Window - Right Panel */}
      <div className="w-[400px] h-full flex flex-col bg-gray-800 border-l border-gray-700">
        <ChatWindow isRecording={false} useOrchestrator={true} />
      </div>
    </main>
  )
}
