'use client';

import React, { useState, useRef, useEffect } from 'react';
import MessageCard, { Message } from './MessageCard';
import InputBar from './InputBar';
import { Shield } from 'lucide-react';
import { motion } from 'framer-motion';

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      role: 'assistant',
      content: 'Hello! I am your DevSec-Brief assistant. Ask me anything about the latest in developer and cybersecurity news.',
    },
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (query: string) => {
    if (!query.trim()) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: query,
    };

    const assistantMessageId = (Date.now() + 1).toString();
    const initialAssistantMessage: Message = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      sources: [],
    };

    setMessages((prev) => [...prev, userMessage, initialAssistantMessage]);
    setIsLoading(true);

    try {
      const response = await fetch('http://127.0.0.1:8000/ask/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, k: 5 }),
      });

      if (!response.body) throw new Error('No response body');

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let done = false;

      let currentEvent = 'message';

      while (!done) {
        const { value, done: doneReading } = await reader.read();
        done = doneReading;
        if (!value) continue;
        
        const chunkValue = decoder.decode(value, { stream: true });
        const lines = chunkValue.split('\n');

        for (let i = 0; i < lines.length; i++) {
          const line = lines[i];
          if (line.startsWith('event: ')) {
            currentEvent = line.replace('event: ', '').trim();
          } else if (line.startsWith('data: ')) {
            const dataStr = line.replace('data: ', '').trim();
            if (dataStr === '[DONE]') continue;

            try {
              const data = JSON.parse(dataStr);
              setMessages((prev) =>
                prev.map((msg) => {
                  if (msg.id === assistantMessageId) {
                    if (currentEvent === 'sources') {
                      return { ...msg, sources: data.sources };
                    } else if (currentEvent === 'token') {
                      return { ...msg, content: msg.content + data.content };
                    } else if (currentEvent === 'error') {
                      return { ...msg, content: 'Error: ' + data.message };
                    }
                  }
                  return msg;
                })
              );
            } catch (e) {
              console.error('Error parsing SSE data:', e, dataStr);
            }
          }
        }
      }
    } catch (error) {
      console.error('Failed to fetch:', error);
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? { ...msg, content: 'Sorry, I encountered an error fetching the response. Please ensure the backend is running.' }
            : msg
        )
      );
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-screen overflow-hidden selection:bg-black/10 dark:selection:bg-white/20">
      {/* Premium Header */}
      <motion.header 
        initial={{ y: -20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5, ease: [0.23, 1, 0.32, 1] }}
        className="flex-shrink-0 flex items-center justify-center p-5 border-b border-black/5 dark:border-white/10 bg-white/60 dark:bg-black/60 backdrop-blur-xl z-10 sticky top-0"
      >
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 bg-black dark:bg-white rounded-lg shadow-sm">
            <Shield className="w-4 h-4 text-white dark:text-black" strokeWidth={2.5} />
          </div>
          <h1 className="font-bold text-[17px] tracking-tight-headers text-black dark:text-white">DevSec-Brief</h1>
        </div>
      </motion.header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto w-full scroll-smooth p-4 sm:p-8 pb-32">
        <div className="max-w-3xl mx-auto flex flex-col">
          {messages.map((msg, index) => (
            <MessageCard key={msg.id} message={msg} />
          ))}
          <div ref={messagesEndRef} className="h-4" />
        </div>
      </div>

      {/* Input */}
      <div className="flex-shrink-0 bg-gradient-to-t from-[var(--background)] via-[var(--background)] to-transparent pt-12 absolute bottom-0 w-full pointer-events-none">
        <div className="pointer-events-auto">
          <InputBar onSubmit={handleSubmit} isLoading={isLoading} />
        </div>
      </div>
    </div>
  );
}
