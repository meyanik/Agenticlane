/** Collapsible card section with chevron, title, and optional badge. */

import { useState, useRef, useEffect } from 'react';

interface CollapsibleSectionProps {
  title: string;
  badge?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

export function CollapsibleSection({ title, badge, defaultOpen = false, children }: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number | undefined>(defaultOpen ? undefined : 0);

  useEffect(() => {
    if (!bodyRef.current) return;
    if (open) {
      setHeight(bodyRef.current.scrollHeight);
      const timer = setTimeout(() => setHeight(undefined), 250);
      return () => clearTimeout(timer);
    } else {
      setHeight(bodyRef.current.scrollHeight);
      requestAnimationFrame(() => setHeight(0));
    }
  }, [open]);

  return (
    <div className={`card collapsible ${open ? 'collapsible-open' : ''}`}>
      <button
        type="button"
        className="collapsible-header"
        onClick={() => setOpen(!open)}
      >
        <span className={`collapsible-chevron ${open ? 'open' : ''}`}>&#9656;</span>
        <span className="collapsible-title">{title}</span>
        {badge && <span className="badge collapsible-badge">{badge}</span>}
      </button>
      <div
        className="collapsible-body"
        ref={bodyRef}
        style={{ height: height === undefined ? 'auto' : height, overflow: 'hidden' }}
      >
        {children}
      </div>
    </div>
  );
}
