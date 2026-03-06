/** Pass/fail/running status badge. */

interface StatusBadgeProps {
  status: string;
  label?: string;
}

const BADGE_CLASSES: Record<string, string> = {
  passed: 'badge-success',
  completed: 'badge-success',
  success: 'badge-success',
  executed: 'badge-success',
  PASS: 'badge-success',
  failed: 'badge-fail',
  FAIL: 'badge-fail',
  tool_crash: 'badge-fail',
  crashed: 'badge-fail',
  partial: 'badge-warn',
  running: 'badge-active',
  active: 'badge-active',
  pruned: 'badge-pruned',
  pending: 'badge-pending',
  unknown: 'badge-pending',
};

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const cls = BADGE_CLASSES[status] || 'badge-pending';
  return <span className={`badge ${cls}`}>{label || status}</span>;
}
