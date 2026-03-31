'use client'
/**
 * WorkflowGeneratorClient — Chat-driven n8n workflow generator.
 *
 * Uses POST /api/v1/agent/chat (stateless agent endpoint) to generate
 * n8n workflow JSON from natural language. Unlike AiChatPanel (which uses
 * /conversations/stream and persists history), this component is intentionally
 * stateless — each session is a fresh workflow-building conversation.
 *
 * SSE event types from /api/v1/agent/chat:
 *   { type: 'token',            content: string }   — streaming LLM token
 *   { type: 'workflow_created', workflow_id: string } — n8n workflow deployed
 *   { type: 'error',            message: string }   — agent error
 *   'data: [DONE]'                                  — stream complete
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import { API_BASE_URL } from '@/lib/api'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
}

interface WorkflowGeneratorClientProps {
  organizationId: string
}

const QUICK_PROMPTS = [
  'Classify ground points and generate a DTM',
  'Remove noise, reproject to WGS84, and write COPC',
  'Extract BIM geometry from an indoor scan',
  'Detect road assets and export GeoJSON',
  'Crop to a bounding box, decimate to 10 cm, export COPC',
]

export default function WorkflowGeneratorClient({ organizationId }: WorkflowGeneratorClientProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        'Hi! I can build an n8n point cloud processing workflow from your description. ' +
        'Tell me what you want to do with your data — e.g. "classify ground, generate DTM, export COPC" — ' +
        'and I\'ll generate and deploy the workflow automatically.',
    },
  ])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [lastWorkflowId, setLastWorkflowId] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || streaming) return
      setInput('')

      const userMsgId = crypto.randomUUID()
      const assistantMsgId = crypto.randomUUID()

      setMessages((prev) => [
        ...prev,
        { id: userMsgId, role: 'user', content: trimmed },
        { id: assistantMsgId, role: 'assistant', content: '' },
      ])
      setStreaming(true)

      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/agent/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: trimmed,
            organization_id: organizationId,
          }),
        })

        if (!res.ok || !res.body) {
          throw new Error(`Agent returned ${res.status}`)
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
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
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, content: m.content + event.content }
                      : m
                  )
                )
              } else if (event.type === 'workflow_created') {
                setLastWorkflowId(event.workflow_id)
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? {
                          ...m,
                          content:
                            m.content +
                            `\n\n✓ Workflow deployed to n8n (ID: \`${event.workflow_id}\`)`,
                        }
                      : m
                  )
                )
              } else if (event.type === 'error') {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, content: `Error: ${event.message}` }
                      : m
                  )
                )
              }
            } catch {
              // Non-JSON line, skip
            }
          }
        }
      } catch (err: unknown) {
        const errMsg = err instanceof Error ? err.message : 'Something went wrong'
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? { ...m, content: `Sorry, I encountered an error: ${errMsg}` }
              : m
          )
        )
      } finally {
        setStreaming(false)
      }
    },
    [streaming, organizationId]
  )

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  const handleReset = () => {
    setMessages([
      {
        id: 'welcome',
        role: 'assistant',
        content:
          'Hi! I can build an n8n point cloud processing workflow from your description. ' +
          'Tell me what you want to do with your data — e.g. "classify ground, generate DTM, export COPC" — ' +
          'and I\'ll generate and deploy the workflow automatically.',
      },
    ])
    setLastWorkflowId(null)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-8 py-5 border-b border-[#1a1a1a]">
        <div>
          <h1 className="text-white text-lg font-semibold tracking-tight">Workflow Generator</h1>
          <p className="text-[#555] text-xs mt-0.5">
            Describe what you want to do — the AI builds and deploys the n8n workflow.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastWorkflowId && (
            <span className="text-xs text-[#555] font-mono bg-[#111] border border-[#1a1a1a] px-3 py-1.5 rounded-lg">
              Last: {lastWorkflowId}
            </span>
          )}
          <button
            onClick={handleReset}
            className="text-xs text-[#555] hover:text-white border border-[#1a1a1a] hover:border-[#333] px-3 py-1.5 rounded-lg transition-colors"
          >
            New session
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-8 py-6 space-y-5">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[75%] rounded-2xl px-5 py-3.5 text-sm leading-relaxed whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-white text-black'
                  : 'bg-[#0d0d0d] text-[#ccc] border border-[#1a1a1a]'
              }`}
            >
              {msg.content || (streaming && msg.role === 'assistant' ? (
                <span className="inline-flex gap-1 items-center">
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

      {/* Quick prompts — only shown at start */}
      {messages.length <= 1 && (
        <div className="px-8 pb-4">
          <p className="text-[#444] text-xs mb-3">Example workflows</p>
          <div className="flex flex-wrap gap-2">
            {QUICK_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                onClick={() => sendMessage(prompt)}
                className="text-xs px-3.5 py-2 bg-[#0d0d0d] border border-[#1a1a1a] text-[#666] rounded-xl hover:border-[#333] hover:text-white transition-colors"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="px-8 py-5 border-t border-[#1a1a1a]">
        <div className="flex gap-3">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={streaming}
            placeholder="Describe your processing workflow in plain English…"
            rows={3}
            className="flex-1 bg-[#0d0d0d] border border-[#1a1a1a] rounded-2xl px-5 py-3.5 text-white text-sm placeholder-[#333] focus:outline-none focus:border-[#2a2a2a] resize-none disabled:opacity-50 leading-relaxed"
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={streaming || !input.trim()}
            className="w-11 h-11 self-end bg-white text-black rounded-xl flex items-center justify-center hover:bg-[#e0e0e0] transition-colors disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
          >
            {streaming ? (
              <span className="w-4 h-4 border-2 border-black border-t-transparent rounded-full animate-spin" />
            ) : (
              <span className="text-base leading-none">↑</span>
            )}
          </button>
        </div>
        <p className="text-[#2a2a2a] text-xs mt-2">Enter to send · Shift+Enter for new line</p>
      </div>
    </div>
  )
}
