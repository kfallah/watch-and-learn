'use client'

import { ReactNode } from 'react'
import { ServiceProvider } from '@/contexts/ServiceContext'

interface ProvidersProps {
  children: ReactNode
}

export default function Providers({ children }: ProvidersProps) {
  return (
    <ServiceProvider>
      {children}
    </ServiceProvider>
  )
}
