/** EventSource hook for SSE live updates. */

import { useState, useEffect, useRef, useCallback } from 'react';
import type { SSEEvent } from '../types';

interface UseSSEResult {
  events: SSEEvent[];
  connected: boolean;
  error: string | null;
}

export function useSSE(url: string | null, maxEvents = 500): UseSSEResult {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const cleanup = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!url) {
      cleanup();
      return;
    }

    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      setConnected(true);
      setError(null);
    };

    es.onerror = () => {
      setConnected(false);
      setError('SSE connection lost');
    };

    // Listen to all event types
    const eventTypes = [
      'metrics_updated', 'evidence_updated', 'judge_votes_updated',
      'composite_score_updated', 'checkpoint_updated', 'patch_updated',
      'manifest_updated',
    ];

    for (const type of eventTypes) {
      es.addEventListener(type, (e: MessageEvent) => {
        try {
          const parsed: SSEEvent = JSON.parse(e.data);
          setEvents(prev => {
            const next = [...prev, parsed];
            return next.length > maxEvents ? next.slice(-maxEvents) : next;
          });
        } catch {
          // Ignore parse errors
        }
      });
    }

    return cleanup;
  }, [url, maxEvents, cleanup]);

  return { events, connected, error };
}
