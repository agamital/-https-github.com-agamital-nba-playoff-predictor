import React, { useState, useRef, useEffect } from 'react';
import { Info } from 'lucide-react';

const ScoringTooltip = ({ content, side = 'top' }) => {
  const [show, setShow] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setShow(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const posClass = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
  }[side] || 'bottom-full left-1/2 -translate-x-1/2 mb-2';

  return (
    <div ref={ref} className="relative inline-flex items-center">
      <button
        type="button"
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
        onClick={() => setShow(v => !v)}
        className="flex items-center justify-center text-slate-500 hover:text-orange-400 transition-colors"
        aria-label="Scoring info"
      >
        <Info className="w-3.5 h-3.5" />
      </button>
      {show && (
        <div className={`absolute ${posClass} z-50 w-56 bg-slate-800 border border-slate-700 rounded-xl shadow-xl p-3 pointer-events-none`}>
          {content}
        </div>
      )}
    </div>
  );
};

export default ScoringTooltip;
