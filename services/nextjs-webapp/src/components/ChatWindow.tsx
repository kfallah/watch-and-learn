'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import RecordingMetadataModal from './RecordingMetadataModal'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  isMarkdown?: boolean
}

interface ChatWindowProps {
  isRecording?: boolean
  useOrchestrator?: boolean
}

/**
 * Simple markdown table renderer
 * Converts markdown tables to HTML tables
 */
function renderMarkdownTable(content: string): React.ReactNode {
  const lines = content.split('\n')
  const elements: React.ReactNode[] = []
  let currentTable: string[] = []
  let inTable = false
  let keyCounter = 0

  const processTable = (tableLines: string[]): React.ReactNode => {
    if (tableLines.length < 2) return null

    const rows = tableLines
      .filter(line => line.trim().startsWith('|'))
      .map(line =>
        line
          .split('|')
          .slice(1, -1)
          .map(cell => cell.trim())
      )

    if (rows.length < 2) return null

    // Check if second row is separator (contains dashes)
    const hasSeparator = rows[1]?.every(cell => /^[-:]+$/.test(cell))
    const headerRow = rows[0]
    const dataRows = hasSeparator ? rows.slice(2) : rows.slice(1)

    return (
      <div key={`table-${keyCounter++}`} className="overflow-x-auto my-2">
        <table className="min-w-full text-sm border border-gray-600">
          <thead className="bg-gray-700">
            <tr>
              {headerRow.map((cell, i) => (
                <th key={i} className="px-3 py-2 text-left border-b border-gray-600">
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dataRows.map((row, rowIdx) => (
              <tr key={rowIdx} className={rowIdx % 2 === 0 ? 'bg-gray-800' : 'bg-gray-750'}>
                {row.map((cell, cellIdx) => (
                  <td key={cellIdx} className="px-3 py-2 border-b border-gray-700">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  for (const line of lines) {
    if (line.trim().startsWith('|')) {
      inTable = true
      currentTable.push(line)
    } else {
      if (inTable && currentTable.length > 0) {
        const tableElement = processTable(currentTable)
        if (tableElement) elements.push(tableElement)
        currentTable = []
        inTable = false
      }
      // Handle headers
      if (line.startsWith('## ')) {
        elements.push(
          <h2 key={`h2-${keyCounter++}`} className="text-lg font-bold mt-3 mb-2">
            {line.slice(3)}
          </h2>
        )
      } else if (line.startsWith('# ')) {
        elements.push(
          <h1 key={`h1-${keyCounter++}`} className="text-xl font-bold mt-3 mb-2">
            {line.slice(2)}
          </h1>
        )
      } else if (line.startsWith('*') && line.endsWith('*') && !line.startsWith('**')) {
        // Italic text (e.g., summary line)
        elements.push(
          <p key={`p-${keyCounter++}`} className="text-gray-400 text-xs mt-2 italic">
            {line.slice(1, -1)}
          </p>
        )
      } else if (line.trim()) {
        elements.push(
          <p key={`p-${keyCounter++}`} className="my-1">
            {line}
          </p>
        )
      }
    }
  }

  // Process any remaining table
  if (currentTable.length > 0) {
    const tableElement = processTable(currentTable)
    if (tableElement) elements.push(tableElement)
  }

  return <div>{elements}</div>
}

export default function ChatWindow({ isRecording = false, useOrchestrator = false }: ChatWindowProps) {
  // Initialize with empty messages to avoid hydration mismatch
  // The welcome message is added after mount via useEffect
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isConnected, setIsConnected] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [showMetadataModal, setShowMetadataModal] = useState(false)
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const prevIsRecordingRef = useRef<boolean>(false)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const connectWebSocket = useCallback(() => {
    // Choose endpoint based on mode
    const wsUrl = useOrchestrator
      ? (typeof window !== 'undefined'
        ? `ws://${window.location.hostname}:8100/ws`
        : 'ws://localhost:8100/ws')
      : (typeof window !== 'undefined'
        ? `ws://${window.location.hostname}:8000/ws`
        : 'ws://localhost:8000/ws')

    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      setIsConnected(true)
      console.log(`Connected to ${useOrchestrator ? 'orchestrator' : 'agent'}`)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'response') {
          // Check if response contains markdown table
          const hasMarkdownTable = data.content.includes('|') && data.content.includes('---')
          setMessages((prev: Message[]) => [
            ...prev,
            {
              id: Date.now().toString(),
              role: 'assistant',
              content: data.content,
              timestamp: new Date(),
              isMarkdown: hasMarkdownTable,
            },
          ])
          setIsLoading(false)
        } else if (data.type === 'status') {
          // Handle status updates (e.g., "thinking", "executing action")
          console.log('Status:', data.content)
          // For orchestrator, show status in chat
          if (useOrchestrator && data.content) {
            setMessages((prev: Message[]) => [
              ...prev,
              {
                id: Date.now().toString(),
                role: 'system',
                content: data.content,
                timestamp: new Date(),
              },
            ])
          }
        } else if (data.type === 'recording_status') {
          // Handle recording status updates
          if (data.session_id) {
            setSessionId(data.session_id)
            console.log('Recording session ID:', data.session_id)
          } else {
            setSessionId(null)
          }
        } else if (data.type === 'error') {
          // Handle error messages
          setMessages((prev: Message[]) => [
            ...prev,
            {
              id: Date.now().toString(),
              role: 'system',
              content: `Error: ${data.content}`,
              timestamp: new Date(),
            },
          ])
          setIsLoading(false)
        }
      } catch (e) {
        console.error('Failed to parse message:', e)
      }
    }

    ws.onclose = () => {
      setIsConnected(false)
      console.log(`Disconnected from ${useOrchestrator ? 'orchestrator' : 'agent'}`)
      // Attempt to reconnect after 3 seconds
      setTimeout(connectWebSocket, 3000)
    }

    ws.onerror = (error) => {
      console.error('WebSocket error:', error)
    }

    wsRef.current = ws
  }, [useOrchestrator])

  useEffect(() => {
    connectWebSocket()

    return () => {
      wsRef.current?.close()
    }
  }, [connectWebSocket])

  // Send recording state changes to backend (only for single-agent mode)
  useEffect(() => {
    // Skip recording functionality in orchestrator mode
    if (useOrchestrator) {
      return
    }

    const updateRecording = async () => {
      // Detect recording stopped (was true, now false)
      const wasRecording = prevIsRecordingRef.current
      const nowRecording = isRecording
      const currentSessionId = sessionId

      // Send via WebSocket for agent mode
      if (isConnected && wsRef.current) {
        wsRef.current.send(
          JSON.stringify({
            type: 'set_recording',
            recording: isRecording,
          })
        )
      }

      // Also call HTTP endpoint for control mode
      try {
        const agentUrl = typeof window !== 'undefined'
          ? `http://${window.location.hostname}:8000`
          : 'http://localhost:8000';

        const endpoint = isRecording ? '/recording/start' : '/recording/stop';
        const response = await fetch(`${agentUrl}${endpoint}`, { method: 'POST' });
        const data = await response.json();

        if (data.session_id) {
          setSessionId(data.session_id);
          console.log('Recording session ID:', data.session_id);
        } else if (!isRecording) {
          setSessionId(null);
        }

        // Show metadata modal when recording stops
        if (wasRecording && !nowRecording && currentSessionId) {
          setPendingSessionId(currentSessionId)
          setShowMetadataModal(true)
        }
      } catch (error) {
        console.error('Failed to update recording state:', error);
      }

      // Update previous recording state
      prevIsRecordingRef.current = isRecording
    };

    updateRecording();
  }, [isRecording, isConnected, useOrchestrator])

  const sendMessage = () => {
    if (!input.trim() || !isConnected || isLoading) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    setIsLoading(true)

    wsRef.current?.send(
      JSON.stringify({
        type: 'message',
        content: input.trim(),
      })
    )

    setInput('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const handleMetadataSubmit = async (description: string) => {
    if (!pendingSessionId) {
      throw new Error('No session ID available')
    }

    const agentUrl = typeof window !== 'undefined'
      ? `http://${window.location.hostname}:8000`
      : 'http://localhost:8000'

    const response = await fetch(`${agentUrl}/recording/metadata`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams({
        session_id: pendingSessionId,
        description,
      }),
    })

    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.message || 'Failed to save metadata')
    }

    // Close modal on success
    setShowMetadataModal(false)
    setPendingSessionId(null)

    // Show success message
    setMessages((prev) => [
      ...prev,
      {
        id: Date.now().toString(),
        role: 'system',
        content: `Recording saved: "${description}"`,
        timestamp: new Date(),
      },
    ])
  }

  const handleMetadataClose = () => {
    setShowMetadataModal(false)
    setPendingSessionId(null)
  }

  return (
    <>
      <RecordingMetadataModal
        isOpen={showMetadataModal}
        sessionId={pendingSessionId || ''}
        onClose={handleMetadataClose}
        onSubmit={handleMetadataSubmit}
      />
      <div className="flex flex-col h-full min-h-0">
        {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 shrink-0">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-white">AI Agent</h2>
          <div className="flex items-center gap-2">
            <div
              className={`w-2 h-2 rounded-full ${
                isConnected ? 'bg-green-500' : 'bg-red-500'
              }`}
            ></div>
            <span className="text-xs text-gray-400">
              {isConnected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
        </div>
        {sessionId && isRecording && (
          <div className="mt-2 text-xs text-gray-500">
            Session: <span className="font-mono">{sessionId}</span>
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
        {messages.map((message: Message) => (
          <div
            key={message.id}
            className={`flex ${
              message.role === 'user' ? 'justify-end' : 'justify-start'
            }`}
          >
            <div
              className={`max-w-[95%] rounded-lg px-4 py-2 ${
                message.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : message.role === 'system'
                  ? 'bg-gray-800 text-gray-300 text-sm italic'
                  : 'bg-gray-700 text-white'
              }`}
            >
              {message.isMarkdown ? (
                renderMarkdownTable(message.content)
              ) : (
                <p className="whitespace-pre-wrap">{message.content}</p>
              )}
              <span className="text-xs opacity-50 mt-1 block">
                {message.timestamp.toLocaleTimeString()}
              </span>
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-700 rounded-lg px-4 py-2">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                <div
                  className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                  style={{ animationDelay: '0.1s' }}
                ></div>
                <div
                  className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                  style={{ animationDelay: '0.2s' }}
                ></div>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-gray-800 shrink-0">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask the agent to do something..."
            className="flex-1 bg-gray-800 text-white rounded-lg px-4 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={1}
            disabled={!isConnected}
          />
          <button
            onClick={sendMessage}
            disabled={!isConnected || !input.trim() || isLoading}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg transition-colors"
          >
            Send
          </button>
        </div>
      </div>
      </div>
    </>
  )
}
