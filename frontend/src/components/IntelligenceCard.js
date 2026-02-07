import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Brain, TrendingUp, TrendingDown, AlertTriangle, Shield, Target, Zap, Activity, Eye, RefreshCw } from 'lucide-react';

const SOCKET_URL = 'http://localhost:5000';

const IntelligenceCard = () => {
  const [loading, setLoading] = useState(true);
  const [learningMetrics, setLearningMetrics] = useState(null);
  const [fraudStatus, setFraudStatus] = useState(null);
  const [predictions, setPredictions] = useState(null);
  const [insights, setInsights] = useState([]);

  const fetchData = useCallback(async () => {
    try {
      const [learningRes, fraudRes, predictionsRes, insightsRes] = await Promise.all([
        axios.get(`${SOCKET_URL}/api/engine/learning`).catch(() => ({ data: null })),
        axios.get(`${SOCKET_URL}/api/fraud/status`).catch(() => ({ data: null })),
        axios.get(`${SOCKET_URL}/api/predictions`).catch(() => ({ data: null })),
        axios.get(`${SOCKET_URL}/api/predictions/insights`).catch(() => ({ data: { insights: [] } }))
      ]);

      setLearningMetrics(learningRes.data);
      setFraudStatus(fraudRes.data);
      setPredictions(predictionsRes.data);
      setInsights(insightsRes.data?.insights || []);
      setLoading(false);
    } catch (err) {
      console.error('Failed to fetch intelligence data');
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const getTrustColor = (score) => {
    if (score >= 0.8) return 'text-emerald-400';
    if (score >= 0.5) return 'text-amber-400';
    return 'text-red-400';
  };

  const getTrendIcon = (trend) => {
    if (trend === 'rising') return <TrendingUp size={14} className="text-red-400" />;
    if (trend === 'falling') return <TrendingDown size={14} className="text-emerald-400" />;
    return <Activity size={14} className="text-slate-400" />;
  };

  if (loading) {
    return (
      <div className="pro-card p-6 animate-pulse">
        <div className="h-6 bg-slate-700 rounded w-48 mb-4"></div>
        <div className="grid grid-cols-3 gap-4">
          <div className="h-24 bg-slate-700 rounded"></div>
          <div className="h-24 bg-slate-700 rounded"></div>
          <div className="h-24 bg-slate-700 rounded"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="pro-card p-6 border border-purple-500/30 bg-gradient-to-br from-slate-900 to-purple-950/30">
      <div className="flex items-center justify-between mb-6">
        <h3 className="font-bold text-lg text-white flex items-center gap-2">
          <Brain className="text-purple-400" />
          AI Intelligence Summary
          <span className="px-2 py-0.5 text-xs bg-purple-500/20 text-purple-400 rounded-full animate-pulse">
            LEARNING
          </span>
        </h3>
        <button 
          onClick={fetchData}
          className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
        >
          <RefreshCw size={16} className="text-slate-400" />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        {/* Mitigation Engine Status */}
        <div className="p-4 bg-slate-800/50 rounded-xl border border-slate-700/50">
          <div className="flex items-center gap-2 mb-3">
            <Shield className="text-blue-400" size={18} />
            <span className="text-slate-300 font-medium">Mitigation Engine</span>
          </div>
          
          {learningMetrics?.source_trust ? (
            <div className="space-y-2">
              {Object.entries(learningMetrics.source_trust).map(([source, data]) => (
                <div key={source} className="flex items-center justify-between">
                  <span className="text-xs text-slate-400 uppercase">{source}</span>
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                      <div 
                        className={`h-full rounded-full transition-all ${
                          data.current >= 0.8 ? 'bg-emerald-500' : 
                          data.current >= 0.5 ? 'bg-amber-500' : 'bg-red-500'
                        }`}
                        style={{ width: `${data.current * 100}%` }}
                      ></div>
                    </div>
                    <span className={`text-xs font-mono ${getTrustColor(data.current)}`}>
                      {(data.current * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              ))}
              
              {learningMetrics.total_feedback > 0 && (
                <div className="mt-3 pt-3 border-t border-slate-700">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-500">Feedback Received</span>
                    <span className="text-purple-400 font-mono">{learningMetrics.total_feedback}</span>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-slate-500">Collecting data...</p>
          )}
        </div>

        {/* Fraud Detection Status */}
        <div className="p-4 bg-slate-800/50 rounded-xl border border-slate-700/50">
          <div className="flex items-center gap-2 mb-3">
            <Eye className="text-red-400" size={18} />
            <span className="text-slate-300 font-medium">Fraud Detection</span>
          </div>
          
          {fraudStatus ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">Accounts Tracked</span>
                <span className="text-white font-mono">{fraudStatus.total_accounts || 0}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">Transactions Analyzed</span>
                <span className="text-white font-mono">{fraudStatus.total_edges || 0}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">Rings Detected</span>
                <span className={`font-mono ${fraudStatus.detected_rings > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                  {fraudStatus.detected_rings || 0}
                </span>
              </div>
              
              {fraudStatus.recent_rings?.length > 0 && (
                <div className="mt-3 pt-3 border-t border-slate-700">
                  <div className="text-xs text-red-400 font-medium mb-2">Active Rings:</div>
                  {fraudStatus.recent_rings.slice(0, 2).map((ring, idx) => (
                    <div key={idx} className="text-xs text-slate-400 truncate">
                      {ring.ring_id}: {ring.ring_type} ({ring.account_count} accounts)
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-slate-500">Initializing...</p>
          )}
        </div>

        {/* Predictive Analytics */}
        <div className="p-4 bg-slate-800/50 rounded-xl border border-slate-700/50">
          <div className="flex items-center gap-2 mb-3">
            <Target className="text-cyan-400" size={18} />
            <span className="text-slate-300 font-medium">Predictions</span>
          </div>
          
          {predictions?.current ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">TPM (5m)</span>
                <div className="flex items-center gap-1">
                  {getTrendIcon(predictions.current.tpm_trend)}
                  <span className="text-white font-mono">
                    {predictions.tpm?.['5m']?.predicted_value?.toFixed(0) || '-'}
                  </span>
                </div>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">Error Rate (5m)</span>
                <div className="flex items-center gap-1">
                  {getTrendIcon(predictions.current.error_trend)}
                  <span className={`font-mono ${
                    (predictions.error_rate?.['5m']?.predicted_value || 0) > 10 ? 'text-red-400' : 'text-white'
                  }`}>
                    {predictions.error_rate?.['5m']?.predicted_value?.toFixed(1) || '0'}%
                  </span>
                </div>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">Avg Amount</span>
                <span className="text-white font-mono">
                  ₹{predictions.current.amount_ema?.toLocaleString() || '0'}
                </span>
              </div>
            </div>
          ) : (
            <p className="text-xs text-slate-500">Building model...</p>
          )}
        </div>
      </div>

      {/* AI Insights */}
      {insights.length > 0 && (
        <div className="border-t border-slate-700 pt-4">
          <h4 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
            <Zap className="text-amber-400" size={14} />
            AI Insights
          </h4>
          <div className="space-y-2">
            {insights.slice(0, 3).map((insight, idx) => (
              <div 
                key={idx}
                className={`p-3 rounded-lg text-sm ${
                  insight.type === 'critical' ? 'bg-red-900/30 border border-red-500/30' :
                  insight.type === 'warning' ? 'bg-amber-900/30 border border-amber-500/30' :
                  'bg-blue-900/30 border border-blue-500/30'
                }`}
              >
                <div className="flex items-start gap-2">
                  <AlertTriangle size={14} className={
                    insight.type === 'critical' ? 'text-red-400' :
                    insight.type === 'warning' ? 'text-amber-400' : 'text-blue-400'
                  } />
                  <div>
                    <p className="text-white">{insight.message}</p>
                    {insight.recommendation && (
                      <p className="text-xs text-slate-400 mt-1">→ {insight.recommendation}</p>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Learning Progress Bar */}
      <div className="mt-4 pt-4 border-t border-slate-700">
        <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
          <span>System Learning Progress</span>
          <span className="text-purple-400">
            {Math.min(100, ((learningMetrics?.total_feedback || 0) + (fraudStatus?.total_edges || 0)) / 10).toFixed(0)}%
          </span>
        </div>
        <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden">
          <div 
            className="h-full bg-gradient-to-r from-purple-500 to-pink-500 rounded-full transition-all duration-1000"
            style={{ 
              width: `${Math.min(100, ((learningMetrics?.total_feedback || 0) + (fraudStatus?.total_edges || 0)) / 10)}%` 
            }}
          ></div>
        </div>
        <p className="text-xs text-slate-500 mt-2">
          The more transactions processed, the smarter the system becomes
        </p>
      </div>
    </div>
  );
};

export default IntelligenceCard;
