import React from 'react';
import Markdown from 'react-markdown';
import { FileText } from 'lucide-react';
import { motion } from 'framer-motion';

export type Source = {
  title: string;
  url: string;
  content_snippet?: string;
};

export type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
};

export default function MessageCard({ message }: { message: Message }) {
  const isUser = message.role === 'user';

  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
      className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} mb-8`}
    >
      <div
        className={`flex flex-col gap-3 ${
          isUser
            ? 'bg-black dark:bg-white text-white dark:text-black rounded-[24px] rounded-br-[8px] py-4 px-6 max-w-[80%] shadow-[0_8px_24px_-12px_rgba(0,0,0,0.2)]'
            : 'premium-card text-black dark:text-white rounded-[24px] rounded-bl-[8px] py-6 px-7 max-w-[95%] sm:max-w-[85%]'
        }`}
      >
        <div
          className={`prose prose-sm md:prose-base dark:prose-invert max-w-none prose-p:leading-relaxed ${
            isUser ? 'text-white dark:text-black' : 'text-zinc-800 dark:text-zinc-200'
          } prose-pre:bg-zinc-100 dark:prose-pre:bg-zinc-900 prose-pre:text-black dark:prose-pre:text-white prose-pre:border prose-pre:border-black/5 dark:prose-pre:border-white/10`}
        >
          <Markdown>{message.content || (isUser ? '' : '...')}</Markdown>
        </div>

        {message.sources && message.sources.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            transition={{ delay: 0.2, duration: 0.4 }}
            className="mt-5 pt-5 border-t border-black/5 dark:border-white/10"
          >
            <h4 className="text-[11px] font-bold uppercase tracking-widest text-zinc-400 dark:text-zinc-500 mb-4 flex items-center gap-2">
              <FileText className="w-3.5 h-3.5" />
              Sources
            </h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {message.sources.map((source, idx) => (
                <a
                  key={idx}
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex flex-col p-4 rounded-[16px] border border-black/5 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.02] hover:bg-black/[0.04] dark:hover:bg-white/[0.05] transition-all duration-300 text-left"
                >
                  <span className="text-sm font-semibold tracking-tight line-clamp-1 group-hover:text-black dark:group-hover:text-white transition-colors">
                    {source.title || (source.url.startsWith('http') ? new URL(source.url).hostname : source.url)}
                  </span>
                  {source.content_snippet && (
                    <span className="text-xs text-zinc-500 dark:text-zinc-400 line-clamp-2 mt-1.5 leading-relaxed">
                      {source.content_snippet}
                    </span>
                  )}
                </a>
              ))}
            </div>
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}
