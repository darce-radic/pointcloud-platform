'use client'

import { useState, useRef, useEffect } from 'react'
import { createClient } from '@/lib/supabase/client'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

interface AiChatPanelProps {
  datasetId: string
  datasetName: string
  onClose: () => void
  onJobStarted: (jobId: string) => void
}

const QUICK_PROMPTS = [
  'Extract floor plan and generate DXF',
  'Detect road markings and traffic signs',
  'Generate a DTM from ground points',
  'Georeference using known control points',
  'Classify and segment all objects',
]

export default function AiChatPanel({ datasetId, datasetName, onClose, onJobStarted }: AiChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '0',
      role: 'assistant',
      content: `I'm your AI assistant for **${datasetName}**. I can create processing workflows, extract features, and answer questions about your point cloud data. What would you like to do?`,
      timestamp: new Date(),
    },
  ])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const supabase = createClient()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = async (text: string) => {
    if (!text.trim() || streaming) return

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: text,
      timestamp: new Date(),
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setStreaming(true)

    const assistantMsgId = (Date.now() + 1).toString()
    setMessages(prev => [...prev, { id: assistantMsgId, role: 'assistant', content: '', timestamp: new Date() }])

    try {
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) throw new Error('Not authenticated')

      const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

      const res = await fetch(`${apiUrl}/api/v1/conversations/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({
          message: text,
          dataset_id: datasetId,
          conversation_id: conversationId,
        }),
      })

      if (!res.ok) throw new Error('Failed to connect to AI agent')

      const reader = res.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (reader) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (data === '[DONE]') continue

          try {
            const event = JSON.parse(data)

            if (event.type === 'token') {
              setMessages(prev => prev.map(m =>
                m.id === assistantMsgId
                  ? { ...m, content: m.content + event.content }
                  : m
              ))
            } else if (event.type === 'conversation_id') {
              setConversationId(event.conversation_id)
            } else if (event.type === 'job_started') {
              onJobStarted(event.job_id)
            } else if (event.type === 'error') {
              setMessages(prev => prev.map(m =>
                m.id === assistantMsgId
                  ? { ...m, content: `Error: ${event.message}` }
                  : m
              ))
            }
          } catch {
            // Non-JSON line, skip
          }
        }
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'Something went wrong'
      setMessages(prev => prev.map(m =>
        m.id === assistantMsgId
          ? { ...m, content: `Sorry, I encountered an error: ${errMsg}` }
          : m
      ))
    } finally {
      setStreaming(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  return (
    <div className="absolute right-0 top-0 bottom-0 w-96 bg-black border-l border-[#1a1a1a] flex flex-col z-30">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-[#1a1a1a]">
        <div>
          <h3 className="text-white text-sm font-medium">AI Assistant</h3>
          <p className="text-[#444] text-xs mt-0.5 truncate max-w-[200px]">{datasetName}</p>
        </div>
        <button onClick={onClose} className="text-[#444] hover:text-white transition-colors text-xl leading-none">×</button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {messages.map(msg => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] rounded-xl px-4 py-3 text-sm ${
              msg.role === 'user'
                ? 'bg-white text-black'
                : 'bg-[#111] text-[#ccc] border border-[#1a1a1a]'
            }`}>
              {msg.content || (streaming && msg.role === 'assistant' ? (
                <span className="inline-flex gap-1">
                  <span className="w-1.5 h-1.5 bg-[#555] rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 bg-[#555] rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 bg-[#555] rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </span>
              ) : '')}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Quick prompts */}
      {messages.length <= 1 && (
        <div className="px-5 pb-3">
          <p className="text-[#444] text-xs mb-2">Quick actions</p>
          <div className="flex flex-wrap gap-1.5">
            {QUICK_PROMPTS.map(prompt => (
              <button
                key={prompt}
                onClick={() => sendMessage(prompt)}
                className="text-xs px-3 py-1.5 bg-[#111] border border-[#1a1a1a] text-[#777] rounded-lg hover:border-[#333] hover:text-white transition-colors"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="px-5 py-4 border-t border-[#1a1a1a]">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={streaming}
            placeholder="Ask anything about your point cloud..."
            rows={2}
            className="flex-1 bg-[#111] border border-[#1a1a1a] rounded-xl px-4 py-3 text-white text-sm placeholder-[#333] focus:outline-none focus:border-[#333] resize-none disabled:opacity-50"
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={streaming || !input.trim()}
            className="w-10 h-10 self-end bg-white text-black rounded-xl flex items-center justify-center hover:bg-[#e0e0e0] transition-colors disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
          >
            {streaming ? (
              <span className="w-3.5 h-3.5 border border-black border-t-transparent rounded-full animate-spin" />
            ) : '↑'}
          </button>
        </div>
        <p className="text-[#333] text-xs mt-2">Enter to send · Shift+Enter for new line</p>
      </div>
    </div>
  )
}
