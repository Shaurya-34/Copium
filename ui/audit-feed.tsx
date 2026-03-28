import React from 'react';

/**
 * CloudCFO Audit Feed Components (Frontend)
 * ----------------------------------------
 * This component renders a list of AWS cost remediations and includes
 * "Open in Slack" buttons using deep-linked deep IDs.
 */

const SLACK_TEAM_ID = "T0AQ7027QSC";
const SLACK_CHANNEL_ID = "C0AP6AEQN3D";

interface AuditEntry {
  id: string;
  timestamp: string;
  resourceId: string;
  action: string;
  status: 'success' | 'failed' | 'manual_review';
  saving: number;
}

export const AuditFeed: React.FC<{ entries: AuditEntry[] }> = ({ entries }) => {
  const openSlackChannel = () => {
    // Deep link to the specific CloudCFO alert channel
    window.location.href = `slack://channel?team=${SLACK_TEAM_ID}&id=${SLACK_CHANNEL_ID}`;
  };

  return (
    <div className="audit-feed-container p-6 bg-slate-900 text-white rounded-xl shadow-2xl">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold font-display">🚀 Remediation Audit Log</h2>
        <button 
          onClick={openSlackChannel}
          className="bg-[#4A154B] hover:bg-[#3b113c] text-white px-4 py-2 rounded-lg flex items-center gap-2 transition-all active:scale-95"
        >
          <img src="https://a.slack-edge.com/80588/img/services/slack_512.png" className="w-5 h-5" alt="Slack" />
          Join CloudCFO Slack
        </button>
      </div>

      <div className="space-y-4">
        {entries.map((entry) => (
          <div key={entry.id} className="p-4 bg-slate-800 border border-slate-700 rounded-lg hover:border-violet-500 transition-colors">
            <div className="flex justify-between items-start">
              <div>
                <span className="text-xs text-slate-400 uppercase tracking-widest">{entry.timestamp}</span>
                <p className="font-mono text-violet-400 mt-1">{entry.resourceId}</p>
                <p className="text-sm mt-2">
                   Executed <span className="font-bold text-white">{entry.action}</span> 
                   {entry.status === 'success' ? ' ✅' : ' ❌'}
                </p>
              </div>
              <div className="text-right">
                <p className="text-green-400 font-bold text-xl">+${entry.saving.toFixed(2)}</p>
                <p className="text-xs text-slate-500">Monthly Savings</p>
              </div>
            </div>
          </div>
        ))}
      </div>
      
      {entries.length === 0 && (
        <div className="text-center py-12 text-slate-500 italic">
          No recent remediations found. Run CloudCFO Scanner.
        </div>
      )}
    </div>
  );
};

export default AuditFeed;
