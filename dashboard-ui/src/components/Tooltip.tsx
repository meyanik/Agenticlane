/** Educational tooltip for VLSI beginners. */

import { useState } from 'react';

interface TooltipProps {
  text: string;
}

export function Tooltip({ text }: TooltipProps) {
  const [show, setShow] = useState(false);

  return (
    <span
      className="tooltip-trigger"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onClick={() => setShow(!show)}
    >
      ?
      {show && (
        <span className="tooltip-content">{text}</span>
      )}
    </span>
  );
}
