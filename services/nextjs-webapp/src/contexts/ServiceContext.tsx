'use client'

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react'

// Types for service discovery response
interface WorkerService {
  id: number
  ws: string
  http: string
}

interface BrowserService {
  id: number
  video_ws: string
  vnc_ws: string
}

interface OrchestratorService {
  ws: string
  http: string
}

interface ServicesConfig {
  orchestrator: OrchestratorService
  workers: WorkerService[]
  browsers: BrowserService[]
  worker_count: number
}

interface ServiceContextValue {
  services: ServicesConfig | null
  isLoading: boolean
  error: string | null
  refetch: () => Promise<void>
}

// Default fallback values (only used if service discovery fails)
const DEFAULT_SERVICES: ServicesConfig = {
  orchestrator: {
    ws: 'ws://localhost:8100/ws',
    http: 'http://localhost:8100',
  },
  workers: [
    { id: 1, ws: 'ws://localhost:8001/ws', http: 'http://localhost:8001' },
    { id: 2, ws: 'ws://localhost:8002/ws', http: 'http://localhost:8002' },
  ],
  browsers: [
    { id: 1, video_ws: 'ws://localhost:8766', vnc_ws: 'ws://localhost:6081' },
    { id: 2, video_ws: 'ws://localhost:8767', vnc_ws: 'ws://localhost:6082' },
  ],
  worker_count: 2,
}

const ServiceContext = createContext<ServiceContextValue | undefined>(undefined)

interface ServiceProviderProps {
  children: ReactNode
  orchestratorUrl?: string
}

export function ServiceProvider({ children, orchestratorUrl }: ServiceProviderProps) {
  const [services, setServices] = useState<ServicesConfig | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Determine orchestrator base URL
  const baseUrl = orchestratorUrl ||
    process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ||
    'http://localhost:8100'

  const fetchServices = async () => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch(`${baseUrl}/services`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const data: ServicesConfig = await response.json()
      setServices(data)
      console.log('[ServiceContext] Discovered services:', data)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      console.warn(`[ServiceContext] Service discovery failed: ${message}, using defaults`)
      setError(message)
      setServices(DEFAULT_SERVICES)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchServices()
  }, [baseUrl])

  return (
    <ServiceContext.Provider value={{ services, isLoading, error, refetch: fetchServices }}>
      {children}
    </ServiceContext.Provider>
  )
}

export function useServices(): ServiceContextValue {
  const context = useContext(ServiceContext)
  if (context === undefined) {
    throw new Error('useServices must be used within a ServiceProvider')
  }
  return context
}

// Convenience hooks for specific services
export function useOrchestratorUrl(): OrchestratorService | null {
  const { services } = useServices()
  return services?.orchestrator || null
}

export function useWorkerUrls(): WorkerService[] {
  const { services } = useServices()
  return services?.workers || []
}

export function useBrowserUrls(): BrowserService[] {
  const { services } = useServices()
  return services?.browsers || []
}

export function useVideoStreamUrls(): string[] {
  const { services } = useServices()
  return services?.browsers.map(b => b.video_ws) || []
}
