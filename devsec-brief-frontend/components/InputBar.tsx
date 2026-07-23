import React, { useState, useRef, useEffect } from 'react';
import { ArrowUp, Mic } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

interface InputBarProps {
  onSubmit: (text: string) => void;
  isLoading: boolean;
}

export default function InputBar({ onSubmit, isLoading }: InputBarProps) {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px';
    }
  }, [input]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      onSubmit(input.trim());
      setInput('');
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="w-full max-w-3xl mx-auto px-4 pb-8 pt-2 relative z-50">
      <motion.form
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5, ease: [0.23, 1, 0.32, 1] }}
        onSubmit={handleSubmit}
        className="relative flex items-end w-full glass-pill rounded-[32px] px-2 py-2 transition-all focus-within:ring-4 focus-within:ring-black/5 dark:focus-within:ring-white/10"
      >
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about DevSec news..."
          className="w-full max-h-[120px] bg-transparent text-black dark:text-white placeholder:text-zinc-400 font-medium tracking-tight border-none focus:ring-0 resize-none outline-none py-3.5 px-5 flex-1 text-base scrollbar-hide"
          rows={1}
          disabled={isLoading}
        />
        <div className="flex items-center gap-2 px-2 pb-1.5 h-full">
          <AnimatePresence mode="wait">
            {input.trim() ? (
              <motion.button
                key="send"
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.8, opacity: 0 }}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                type="submit"
                disabled={isLoading}
                className="p-3 bg-black dark:bg-white text-white dark:text-black rounded-full hover:bg-zinc-800 dark:hover:bg-zinc-200 transition-colors disabled:opacity-50 flex-shrink-0 shadow-md"
              >
                <ArrowUp className="w-4 h-4" strokeWidth={3} />
              </motion.button>
            ) : (
              <motion.button
                key="mic"
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.8, opacity: 0 }}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                type="button"
                className="p-3 text-zinc-400 hover:text-black dark:hover:text-white transition-colors flex-shrink-0"
                title="Voice input (mock)"
              >
                <Mic className="w-5 h-5" />
              </motion.button>
            )}
          </AnimatePresence>
        </div>
      </motion.form>
    </div>
  );
}
