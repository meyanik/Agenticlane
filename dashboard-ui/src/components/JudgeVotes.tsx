/** Judge vote visualization. */

import { StatusBadge } from './StatusBadge';
import type { JudgeAggregate } from '../types';

interface JudgeVotesProps {
  aggregate: JudgeAggregate;
}

export function JudgeVotes({ aggregate }: JudgeVotesProps) {
  const { votes, result, confidence, blocking_issues } = aggregate;

  return (
    <div className="judge-votes">
      <div className="judge-header">
        <StatusBadge status={result} />
        <span className="judge-confidence">
          Confidence: {(confidence * 100).toFixed(0)}%
        </span>
      </div>

      {votes.length > 0 && (
        <div className="judge-vote-list">
          {votes.map((v, i) => (
            <div key={i} className="judge-vote-item">
              <span className="judge-model">{v.model}</span>
              <StatusBadge status={v.vote} />
              <span className="judge-vote-conf">
                {((v.confidence || 0) * 100).toFixed(0)}%
              </span>
              {v.reason && (
                <span className="judge-reason">{v.reason}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {blocking_issues.length > 0 && (
        <div className="judge-blocking">
          <strong>Blocking Issues:</strong>
          <ul>
            {blocking_issues.map((issue, i) => (
              <li key={i}>
                <span className="tag">{issue.metric_key}</span>
                {' '}{issue.description}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
