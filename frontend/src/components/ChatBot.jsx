import React, { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { MessageCircle, Send, X, Bot, Sparkles } from 'lucide-react';
import { sendChatMessage } from '../services/api';

const WELCOME_MESSAGE = {
  role: 'assistant',
  content: "Hey! 🏀 I'm your NBA Picks AI.\nAsk me who to pick, what the community thinks, how scoring works, or check your ranking.\n\nאפשר גם לשאול אותי בעברית — אני מבין הכל! 🇮🇱",
};

const SUGGESTION_CHIPS = [
  "Who should I pick to win the West?",
  "מה הקהילה חושבת על OKC?",
  "How do underdog picks score?",
  "כמה נקודות אני יכול להרוויח עכשיו?",
];

export default function ChatBot({ currentUser }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([WELCOME_MESSAGE]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [showChips, setShowChips] = useState(true);
  const endRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll to latest message
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Focus input when panel opens
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 150);
    }
  }, [open]);

  const send = async (textOverride) => {
    const text = (textOverride ?? input).trim();
    if (!text || loading) return;

    const userMsg = { role: 'user', content: text };
    const nextMessages = [...messages, userMsg];
    setMessages(nextMessages);
    setInput('');
    setShowChips(false);
    setLoading(true);

    try {
      // Skip the static welcome message when sending to API; cap at last 10
      const historyToSend = nextMessages.slice(1).slice(-10);
      const { reply } = await sendChatMessage(
        historyToSend,
        currentUser?.user_id ?? null,
      );
      setMessages(prev => [...prev, { role: 'assistant', content: reply }]);
    } catch {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: "Sorry, I had trouble connecting. Please try again! 🙏" },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const handleChip = (chip) => {
    send(chip);
  };

  const panel = open && (
    <div
      className="fixed bottom-[100px] right-4 md:bottom-24 md:right-6 z-[60]
                 flex flex-col bg-slate-900 border border-slate-700/80 rounded-2xl
                 shadow-2xl shadow-black/70 overflow-hidden"
      style={{ width: 'min(380px, calc(100vw - 2rem))', height: 490 }}
    >
      {/* ── Header ── */}
      <div className="flex items-center gap-3 px-4 py-3 bg-gradient-to-r from-orange-500 to-red-600 shrink-0">
        <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center shrink-0">
          <Bot className="w-4 h-4 text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-black text-white leading-none">NBA Picks AI</p>
          <p className="text-[10px] text-orange-100/80 mt-0.5 leading-none">Ask anything about picks & scoring</p>
        </div>
        <button
          onClick={() => setOpen(false)}
          className="w-7 h-7 rounded-full bg-white/10 hover:bg-white/25 flex items-center justify-center transition-colors shrink-0"
          aria-label="Close chat"
        >
          <X className="w-4 h-4 text-white" />
        </button>
      </div>

      {/* ── Messages ── */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {m.role === 'assistant' && (
              <div className="w-6 h-6 rounded-full bg-orange-500/20 border border-orange-500/30 flex items-center justify-center mr-2 mt-0.5 shrink-0">
                <Bot className="w-3 h-3 text-orange-400" />
              </div>
            )}
            <div
              dir="auto"
              className={`max-w-[82%] rounded-2xl px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap
                ${m.role === 'user'
                  ? 'bg-orange-500 text-white rounded-br-sm font-medium'
                  : 'bg-slate-800 text-slate-200 border border-slate-700/60 rounded-bl-sm'
                }`}
            >
              {m.content}
            </div>
          </div>
        ))}

        {/* Typing indicator */}
        {loading && (
          <div className="flex justify-start items-end gap-2">
            <div className="w-6 h-6 rounded-full bg-orange-500/20 border border-orange-500/30 flex items-center justify-center shrink-0">
              <Bot className="w-3 h-3 text-orange-400" />
            </div>
            <div className="bg-slate-800 border border-slate-700/60 rounded-2xl rounded-bl-sm px-3 py-2.5">
              <div className="flex gap-1 items-center">
                <span className="w-1.5 h-1.5 bg-orange-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 bg-orange-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 bg-orange-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}

        {/* Suggestion chips (shown only at start) */}
        {showChips && messages.length === 1 && !loading && (
          <div className="pt-1 space-y-1.5">
            <p className="text-[10px] text-slate-500 uppercase font-bold tracking-wider px-1">Try asking...</p>
            {SUGGESTION_CHIPS.map((chip, i) => (
              <button
                key={i}
                onClick={() => handleChip(chip)}
                className="w-full text-left px-3 py-1.5 rounded-xl bg-slate-800/60 border border-slate-700/50
                           hover:border-orange-500/50 hover:bg-slate-800 text-xs text-slate-300
                           hover:text-orange-300 transition-all"
              >
                {chip}
              </button>
            ))}
          </div>
        )}

        <div ref={endRef} />
      </div>

      {/* ── Input ── */}
      <div className="shrink-0 border-t border-slate-700/80 px-3 py-2.5 flex gap-2 items-end bg-slate-900/50">
        <input
          ref={inputRef}
          dir="auto"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask / שאל אותי על הפלייאוף..."
          disabled={loading}
          className="flex-1 bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white
                     placeholder-slate-500 focus:outline-none focus:border-orange-500/70 transition-colors
                     disabled:opacity-50 resize-none"
        />
        <button
          onClick={() => send()}
          disabled={loading || !input.trim()}
          className="w-9 h-9 rounded-xl bg-orange-500 hover:bg-orange-600 active:bg-orange-700
                     disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center
                     transition-all shrink-0"
          aria-label="Send message"
        >
          <Send className="w-4 h-4 text-white" />
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* ── Floating button ── */}
      <button
        onClick={() => setOpen(o => !o)}
        className="fixed bottom-[88px] right-4 md:bottom-8 md:right-6 z-[55]
                   w-14 h-14 rounded-full bg-gradient-to-br from-orange-500 to-red-600
                   shadow-lg shadow-orange-500/30 hover:shadow-orange-500/50
                   flex items-center justify-center transition-all duration-200
                   active:scale-95 hover:scale-105"
        aria-label={open ? 'Close AI assistant' : 'Open NBA AI assistant'}
      >
        {open
          ? <X className="w-6 h-6 text-white" />
          : <MessageCircle className="w-6 h-6 text-white" />
        }
        {/* Pulse ring — shown when closed to attract attention */}
        {!open && (
          <span className="absolute inset-0 rounded-full bg-orange-500/40 animate-ping" />
        )}
      </button>

      {createPortal(panel, document.body)}
    </>
  );
}
