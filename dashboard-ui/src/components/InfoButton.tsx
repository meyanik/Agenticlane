/** (i) info button with click-to-open popover for deep explanations. */

import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';

interface InfoButtonProps {
  title: string;
  content: string;
}

export function InfoButton({ title, content }: InfoButtonProps) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  const updatePos = useCallback(() => {
    if (!btnRef.current) return;
    const rect = btnRef.current.getBoundingClientRect();
    const popW = 360;
    // Try above; if not enough room, go below
    const spaceAbove = rect.top;
    const goBelow = spaceAbove < 200;
    let left = rect.left + rect.width / 2 - popW / 2;
    // Clamp to viewport
    if (left < 8) left = 8;
    if (left + popW > window.innerWidth - 8) left = window.innerWidth - popW - 8;
    setPos({
      top: goBelow ? rect.bottom + 8 : rect.top - 8,
      left,
    });
  }, []);

  useEffect(() => {
    if (!open) return;
    updatePos();
    const handleClick = (e: MouseEvent) => {
      if (
        btnRef.current?.contains(e.target as Node) ||
        popoverRef.current?.contains(e.target as Node)
      ) return;
      setOpen(false);
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    const handleScroll = () => updatePos();
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    window.addEventListener('scroll', handleScroll, true);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
      window.removeEventListener('scroll', handleScroll, true);
    };
  }, [open, updatePos]);

  const goBelow = btnRef.current ? btnRef.current.getBoundingClientRect().top < 200 : false;

  return (
    <>
      <button
        type="button"
        className="info-btn"
        ref={btnRef}
        onClick={() => setOpen(!open)}
        aria-label={`Info: ${title}`}
      >
        i
      </button>
      {open && createPortal(
        <div
          className="info-popover"
          ref={popoverRef}
          style={{
            position: 'fixed',
            top: goBelow ? pos.top : undefined,
            bottom: goBelow ? undefined : `${window.innerHeight - pos.top}px`,
            left: pos.left,
          }}
        >
          <div className="info-popover-title">{title}</div>
          <div className="info-popover-body">{content}</div>
        </div>,
        document.body,
      )}
    </>
  );
}
