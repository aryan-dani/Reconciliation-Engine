import React, { useState, useEffect, useCallback, useRef } from "react";
import io from "socket.io-client";
import axios from "axios";
import {
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  Shield,
  LayoutDashboard,
  FileText,
  Settings,
  Bell,
  LogOut,
  TrendingUp,
  AlertOctagon,
  RefreshCw,
  Globe,
  Smartphone,
  Server,
  CreditCard,
  X,
  Volume2,
  VolumeX,
  Zap,
  Eye,
  Play,
  Pause,
  Gauge,
  Wifi,
  WifiOff,
  Database,
  Clock,
  ArrowUpRight,
  BarChart3,
  Target,
  Cpu,
  HardDrive,
  Bot,
  ShieldCheck,
  ShieldAlert,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Brain,
  Lock,
  Unlock,
  Info,
  Maximize2,
  MessageSquare,
  Lightbulb,
  ExternalLink,
  Banknote,
} from "lucide-react";
import "./App.css";

const SOCKET_URL = "http://localhost:5000";

// Create socket with reconnection options
const createSocket = () => {
  return io(SOCKET_URL, {
    reconnection: true,
    reconnectionAttempts: Infinity,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
    timeout: 20000,
    transports: ["websocket", "polling"],
  });
};

let socket = createSocket();

// Sound alert for critical issues
const playAlertSound = () => {
  const audioContext = new (window.AudioContext || window.webkitAudioContext)();
  const oscillator = audioContext.createOscillator();
  const gainNode = audioContext.createGain();

  oscillator.connect(gainNode);
  gainNode.connect(audioContext.destination);

  oscillator.frequency.value = 800;
  oscillator.type = "sine";
  gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
  gainNode.gain.exponentialRampToValueAtTime(
    0.01,
    audioContext.currentTime + 0.5
  );

  oscillator.start(audioContext.currentTime);
  oscillator.stop(audioContext.currentTime + 0.5);
};

// Currency symbols mapping
const CURRENCY_SYMBOLS = {
  INR: "₹",
  USD: "$",
  GBP: "£",
  EUR: "€",
  SGD: "S$",
  AED: "د.إ",
  AUD: "A$",
  JPY: "¥",
  CAD: "C$",
};

// Format amount with currency support
const formatCurrency = (amount, currency = "INR") => {
  if (!amount && amount !== 0)
    return `${CURRENCY_SYMBOLS[currency] || currency}0`;
  const num = parseFloat(amount);
  const symbol = CURRENCY_SYMBOLS[currency] || currency + " ";

  if (currency === "INR") {
    // Indian numbering system
    if (num >= 10000000) {
      return `${symbol}${(num / 10000000).toFixed(2)} Cr`;
    } else if (num >= 100000) {
      return `${symbol}${(num / 100000).toFixed(2)} L`;
    } else {
      return `${symbol}${num.toLocaleString("en-IN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;
    }
  } else {
    // Western numbering system
    if (num >= 1000000) {
      return `${symbol}${(num / 1000000).toFixed(2)}M`;
    } else if (num >= 1000) {
      return `${symbol}${(num / 1000).toFixed(1)}K`;
    } else {
      return `${symbol}${num.toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;
    }
  }
};

// Legacy support - format amount in Indian Rupees
const formatINR = (amount) => formatCurrency(amount, "INR");

// Mismatch type colors for pie chart
const MISMATCH_COLORS = {
  AMOUNT_MISMATCH: "#ef4444",
  STATUS_MISMATCH: "#f59e0b",
  MISSING_CBS: "#8b5cf6",
  MISSING_MOBILE: "#06b6d4",
  TIMESTAMP_DRIFT: "#10b981",
  FRAUD: "#dc2626",
  GHOST: "#6366f1",
  UNKNOWN: "#64748b",
};

// Content Safety Severity Badge Component
const ContentSafetyBadge = ({ safety }) => {
  if (!safety || safety.enabled === false) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-slate-700/50 text-slate-400 border border-slate-600/50">
        <ShieldAlert size={12} />
        Safety Disabled
      </span>
    );
  }

  if (!safety.ok) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-amber-500/20 text-amber-400 border border-amber-500/30">
        <ShieldAlert size={12} />
        Check Error
      </span>
    );
  }

  if (safety.allowed === false) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse">
        <Lock size={12} />
        Blocked (Severity: {safety.max_severity})
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
      <ShieldCheck size={12} />
      Safe (Max: {safety.max_severity || 0})
    </span>
  );
};

// Helper function to normalize Content Safety categories
// Backend can return either array [{category: "Hate", severity: 2}] or object {Hate: 2}
const normalizeCategories = (categories) => {
  if (!categories) return [];

  // If it's an array (Azure format), transform to [{name, severity}]
  if (Array.isArray(categories)) {
    return categories.map((item) => ({
      name: item.category || item.name || "Unknown",
      severity: typeof item.severity === "number" ? item.severity : 0,
    }));
  }

  // If it's an object {Hate: 2}, transform to [{name, severity}]
  if (typeof categories === "object") {
    return Object.entries(categories).map(([name, value]) => ({
      name,
      severity: typeof value === "number" ? value : value?.severity || 0,
    }));
  }

  return [];
};

// Content Safety Details Component
const ContentSafetyDetails = ({ safety }) => {
  if (!safety || safety.enabled === false) return null;

  const categoryList = normalizeCategories(safety.categories);

  return (
    <div className="mt-3 p-3 bg-slate-900/50 rounded-lg border border-slate-700/50">
      <div className="flex items-center gap-2 mb-2">
        <Shield size={14} className="text-cyan-400" />
        <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
          Content Safety Analysis
        </span>
      </div>
      {categoryList.length > 0 ? (
        <div className="grid grid-cols-2 gap-2">
          {categoryList.map((cat, idx) => (
            <div
              key={cat.name || idx}
              className="flex items-center justify-between p-2 bg-slate-800/50 rounded"
            >
              <span className="text-xs text-slate-400 capitalize">
                {String(cat.name).replace(/_/g, " ")}
              </span>
              <span
                className={`text-xs font-mono font-bold ${
                  cat.severity >= 4
                    ? "text-red-400"
                    : cat.severity >= 2
                    ? "text-amber-400"
                    : "text-emerald-400"
                }`}
              >
                {cat.severity}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-500">No category data available</p>
      )}
    </div>
  );
};

// AI Insight Panel Component
const AIInsightPanel = ({ ai, expanded, onToggle }) => {
  if (!ai) return null;

  const isError = ai.ok === false;
  const analysis = ai.analysis || "No analysis available";
  const contentSafety = ai.content_safety;

  return (
    <div
      className={`rounded-xl border transition-all duration-300 ${
        isError
          ? "bg-red-500/10 border-red-500/30"
          : "bg-gradient-to-br from-blue-500/10 to-purple-500/10 border-blue-500/30"
      }`}
    >
      {/* Header */}
      <button
        onClick={onToggle}
        className="w-full p-4 flex items-center justify-between text-left hover:bg-white/5 transition-colors rounded-t-xl"
      >
        <div className="flex items-center gap-3">
          <div
            className={`p-2 rounded-lg ${
              isError ? "bg-red-500/20" : "bg-blue-500/20"
            }`}
          >
            <Brain
              size={20}
              className={isError ? "text-red-400" : "text-blue-400"}
            />
          </div>
          <div>
            <h4 className="font-semibold text-white flex items-center gap-2">
              AI Analysis
              <Sparkles size={14} className="text-purple-400" />
            </h4>
            <p className="text-xs text-slate-400">
              Powered by Azure AI Foundry
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {contentSafety && <ContentSafetyBadge safety={contentSafety} />}
          {expanded ? (
            <ChevronUp size={20} className="text-slate-400" />
          ) : (
            <ChevronDown size={20} className="text-slate-400" />
          )}
        </div>
      </button>

      {/* Expanded Content */}
      {expanded && (
        <div className="px-4 pb-4 space-y-4 animate-fade-in">
          {/* Status Badge */}
          <div className="flex items-center gap-2">
            {ai.ok ? (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                <CheckCircle size={12} />
                Analysis Complete
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-red-500/20 text-red-400 border border-red-500/30">
                <AlertOctagon size={12} />
                {ai.error_code || "Analysis Error"}
              </span>
            )}
            {ai.trace_id && (
              <span className="text-xs text-slate-500 font-mono">
                trace: {ai.trace_id.slice(0, 8)}...
              </span>
            )}
          </div>

          {/* Analysis Text */}
          <div className="p-4 bg-slate-900/70 rounded-lg border border-slate-700/50">
            <div className="flex items-start gap-3">
              <Bot size={18} className="text-purple-400 mt-0.5 flex-shrink-0" />
              <div className="flex-1">
                <p className="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">
                  {analysis}
                </p>
              </div>
            </div>
          </div>

          {/* Structured Data */}
          {ai.raw && (
            <div className="space-y-3">
              {ai.raw.severity && (
                <div className="flex items-center justify-between p-3 bg-slate-900/50 rounded-lg">
                  <span className="text-sm text-slate-400">AI Severity</span>
                  <span
                    className={`px-2.5 py-1 rounded-full text-xs font-bold uppercase ${
                      ai.raw.severity === "critical"
                        ? "bg-red-500/20 text-red-400 border border-red-500/30"
                        : ai.raw.severity === "high"
                        ? "bg-orange-500/20 text-orange-400 border border-orange-500/30"
                        : ai.raw.severity === "medium"
                        ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                        : "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                    }`}
                  >
                    {ai.raw.severity}
                  </span>
                </div>
              )}

              {ai.raw.confidence !== undefined && (
                <div className="p-3 bg-slate-900/50 rounded-lg">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm text-slate-400">
                      AI Confidence
                    </span>
                    <span className="text-sm font-mono text-white">
                      {Math.round(ai.raw.confidence * 100)}%
                    </span>
                  </div>
                  <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-blue-500 to-purple-500 rounded-full transition-all duration-500"
                      style={{ width: `${ai.raw.confidence * 100}%` }}
                    ></div>
                  </div>
                </div>
              )}

              {ai.raw.recommended_action && (
                <div className="p-3 bg-slate-900/50 rounded-lg">
                  <span className="text-xs text-slate-500 uppercase tracking-wider">
                    Recommended Action
                  </span>
                  <p className="text-sm text-white mt-1 font-medium">
                    {ai.raw.recommended_action}
                  </p>
                </div>
              )}

              {ai.raw.root_cause && (
                <div className="p-3 bg-slate-900/50 rounded-lg">
                  <span className="text-xs text-slate-500 uppercase tracking-wider">
                    Root Cause
                  </span>
                  <p className="text-sm text-slate-300 mt-1">
                    {ai.raw.root_cause}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Content Safety Details */}
          {contentSafety && <ContentSafetyDetails safety={contentSafety} />}

          {/* Error Details */}
          {isError && ai.hint && (
            <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
              <div className="flex items-center gap-2 text-red-400 text-sm">
                <Info size={14} />
                <span className="font-medium">Error Details</span>
              </div>
              <p className="text-xs text-red-300/70 mt-1">
                {typeof ai.hint === "string"
                  ? ai.hint
                  : JSON.stringify(ai.hint)}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// Full-Screen AI Analysis Drawer
const AIDrawer = ({ alert, onClose, onViewTransaction }) => {
  if (!alert) return null;

  const ai = alert.ai;
  const isError = ai?.ok === false;
  const analysis =
    ai?.analysis || "No AI analysis available for this transaction.";
  const contentSafety = ai?.content_safety;

  return (
    <>
      {/* Overlay */}
      <div className="ai-drawer-overlay" onClick={onClose} />

      {/* Drawer Panel */}
      <div className="ai-drawer">
        {/* Header */}
        <div className="flex-shrink-0 p-6 border-b border-slate-700/50 bg-gradient-to-r from-slate-900 to-slate-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="p-3 rounded-xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-blue-500/30">
                <Brain size={24} className="text-blue-400" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  AI Analysis
                  <Sparkles size={18} className="text-purple-400" />
                </h2>
                <p className="text-sm text-slate-400">
                  Powered by Azure AI Foundry
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-slate-700/50 rounded-lg transition-colors"
            >
              <X size={24} className="text-slate-400" />
            </button>
          </div>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 ai-panel-scroll">
          {/* Transaction Summary */}
          <div className="pro-card p-5">
            <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
              <FileText size={14} />
              Transaction Details
            </h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="p-3 bg-slate-900/50 rounded-lg">
                <span className="text-xs text-slate-500">Transaction ID</span>
                <p className="text-sm font-mono text-white mt-1">
                  {alert.id?.slice(0, 16)}...
                </p>
              </div>
              <div className="p-3 bg-slate-900/50 rounded-lg">
                <span className="text-xs text-slate-500">Amount</span>
                <p className="text-sm font-bold text-white mt-1">
                  {formatINR(alert.amount)}
                </p>
              </div>
              <div className="p-3 bg-slate-900/50 rounded-lg">
                <span className="text-xs text-slate-500">Status</span>
                <p
                  className={`text-sm font-semibold mt-1 ${
                    alert.severity === "error"
                      ? "text-red-400"
                      : alert.severity === "warning"
                      ? "text-amber-400"
                      : "text-emerald-400"
                  }`}
                >
                  {alert.severity?.toUpperCase()}
                </p>
              </div>
              <div className="p-3 bg-slate-900/50 rounded-lg">
                <span className="text-xs text-slate-500">Timestamp</span>
                <p className="text-sm text-slate-300 mt-1">{alert.timestamp}</p>
              </div>
            </div>
          </div>

          {/* AI Status Badges */}
          <div className="flex flex-wrap gap-3">
            {ai?.ok ? (
              <span className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                <CheckCircle size={16} />
                Analysis Complete
              </span>
            ) : (
              <span className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium bg-red-500/20 text-red-400 border border-red-500/30">
                <AlertOctagon size={16} />
                {ai?.error_code || "Analysis Error"}
              </span>
            )}
            {contentSafety && <ContentSafetyBadge safety={contentSafety} />}
            {ai?.trace_id && (
              <span className="inline-flex items-center gap-2 px-3 py-2 rounded-full text-xs font-mono text-slate-500 bg-slate-800/50 border border-slate-700/50">
                Trace: {ai.trace_id.slice(0, 12)}...
              </span>
            )}
          </div>

          {/* Main AI Analysis */}
          <div className="ai-message">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
                  <Bot size={20} className="text-white" />
                </div>
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-sm font-semibold text-white">
                    AI Assistant
                  </span>
                  <span className="text-xs text-slate-500">
                    Azure AI Foundry
                  </span>
                </div>
                <div className="prose prose-invert prose-sm max-w-none">
                  <p className="text-base text-slate-200 leading-relaxed whitespace-pre-wrap">
                    {analysis}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Structured AI Data */}
          {ai?.raw && (
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2">
                <BarChart3 size={14} />
                Analysis Metrics
              </h3>

              {/* Severity */}
              {ai.raw.severity && (
                <div className="pro-card p-5">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-sm text-slate-400 flex items-center gap-2">
                      <AlertTriangle size={14} />
                      Risk Severity
                    </span>
                    <span
                      className={`px-4 py-1.5 rounded-full text-sm font-bold uppercase ${
                        ai.raw.severity === "critical"
                          ? "bg-red-500/20 text-red-400 border border-red-500/30"
                          : ai.raw.severity === "high"
                          ? "bg-orange-500/20 text-orange-400 border border-orange-500/30"
                          : ai.raw.severity === "medium"
                          ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                          : "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                      }`}
                    >
                      {ai.raw.severity}
                    </span>
                  </div>
                </div>
              )}

              {/* Confidence Score */}
              {ai.raw.confidence !== undefined && (
                <div className="pro-card p-5">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-sm text-slate-400 flex items-center gap-2">
                      <Target size={14} />
                      AI Confidence
                    </span>
                    <span className="text-lg font-bold text-white font-mono">
                      {Math.round(ai.raw.confidence * 100)}%
                    </span>
                  </div>
                  <div className="h-3 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-blue-500 via-purple-500 to-pink-500 rounded-full transition-all duration-700"
                      style={{ width: `${ai.raw.confidence * 100}%` }}
                    />
                  </div>
                </div>
              )}

              {/* Recommended Action */}
              {ai.raw.recommended_action && (
                <div className="pro-card p-5">
                  <div className="flex items-start gap-3">
                    <div className="p-2 rounded-lg bg-emerald-500/20 border border-emerald-500/30">
                      <Lightbulb size={18} className="text-emerald-400" />
                    </div>
                    <div>
                      <span className="text-xs text-slate-500 uppercase tracking-wider">
                        Recommended Action
                      </span>
                      <p className="text-base text-white mt-1 font-medium">
                        {ai.raw.recommended_action}
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Root Cause */}
              {ai.raw.root_cause && (
                <div className="pro-card p-5">
                  <div className="flex items-start gap-3">
                    <div className="p-2 rounded-lg bg-amber-500/20 border border-amber-500/30">
                      <MessageSquare size={18} className="text-amber-400" />
                    </div>
                    <div>
                      <span className="text-xs text-slate-500 uppercase tracking-wider">
                        Root Cause Analysis
                      </span>
                      <p className="text-base text-slate-300 mt-1">
                        {ai.raw.root_cause}
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Content Safety Details */}
          {contentSafety && contentSafety.enabled !== false && (
            <div className="pro-card p-5">
              <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
                <Shield size={14} className="text-cyan-400" />
                Content Safety Analysis
              </h3>

              <div className="flex items-center gap-3 mb-4">
                {contentSafety.allowed === false ? (
                  <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-500/20 border border-red-500/30">
                    <Lock size={16} className="text-red-400" />
                    <span className="text-red-400 font-medium">
                      Content Blocked
                    </span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500/20 border border-emerald-500/30">
                    <Unlock size={16} className="text-emerald-400" />
                    <span className="text-emerald-400 font-medium">
                      Content Approved
                    </span>
                  </div>
                )}
                <span className="text-sm text-slate-500">
                  Max Severity:{" "}
                  <span className="font-mono text-white">
                    {contentSafety.max_severity || 0}
                  </span>
                </span>
              </div>

              {contentSafety.categories &&
                (Array.isArray(contentSafety.categories)
                  ? contentSafety.categories.length > 0
                  : Object.keys(contentSafety.categories).length > 0) && (
                  <div className="grid grid-cols-2 gap-3">
                    {normalizeCategories(contentSafety.categories).map(
                      (cat, idx) => (
                        <div
                          key={cat.name || idx}
                          className="flex items-center justify-between p-3 bg-slate-900/50 rounded-lg"
                        >
                          <span className="text-sm text-slate-400 capitalize">
                            {String(cat.name).replace(/_/g, " ")}
                          </span>
                          <span
                            className={`text-sm font-mono font-bold ${
                              cat.severity >= 4
                                ? "text-red-400"
                                : cat.severity >= 2
                                ? "text-amber-400"
                                : "text-emerald-400"
                            }`}
                          >
                            {cat.severity}
                          </span>
                        </div>
                      )
                    )}
                  </div>
                )}
            </div>
          )}

          {/* Error Details */}
          {isError && ai?.hint && (
            <div className="pro-card p-5 border-red-500/30 bg-red-500/5">
              <div className="flex items-center gap-2 text-red-400 mb-3">
                <Info size={16} />
                <span className="font-semibold">Error Details</span>
              </div>
              <p className="text-sm text-red-300/80">
                {typeof ai.hint === "string"
                  ? ai.hint
                  : JSON.stringify(ai.hint)}
              </p>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="flex-shrink-0 p-4 border-t border-slate-700/50 bg-slate-900/50">
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="flex-1 px-4 py-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-white font-medium transition-colors"
            >
              Close
            </button>
            <button
              onClick={() => {
                if (onViewTransaction) {
                  onViewTransaction(alert.id, alert);
                }
                onClose();
              }}
              className="flex-1 px-4 py-3 rounded-xl bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white font-medium transition-colors flex items-center justify-center gap-2"
            >
              <ExternalLink size={16} />
              View Full Transaction
            </button>
          </div>
        </div>
      </div>
    </>
  );
};

// Transaction Detail Modal Component
const TransactionModal = ({ txId, token, onClose, alertData }) => {
  const [txData, setTxData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [aiExpanded, setAiExpanded] = useState(true);

  useEffect(() => {
    const fetchTransaction = async () => {
      try {
        const res = await axios.get(`${SOCKET_URL}/api/transaction/${txId}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        setTxData(res.data);
      } catch (err) {
        console.error("Failed to fetch transaction details");
        // txData will remain null, we'll use alertData
      }
      setLoading(false);
    };
    fetchTransaction();
  }, [txId, token]);

  // Merge alertData with fetched txData for AI insights
  const ai = alertData?.ai || txData?.ai;

  // Use txData if available, otherwise fall back to alertData
  const displayId = txData?.tx_id || alertData?.id || txId;
  const displayStatus =
    txData?.status ||
    (alertData?.severity === "error"
      ? "MISMATCH"
      : alertData?.severity === "warning"
      ? "WARNING"
      : "MATCHED");
  const displayAmount =
    txData?.sources?.payment_gateway?.amount || alertData?.amount;
  const displayCurrency =
    txData?.sources?.payment_gateway?.currency || alertData?.currency || "INR";
  const displayCountry =
    txData?.sources?.payment_gateway?.country || alertData?.country;
  const displayMismatchType = txData?.mismatch_type || alertData?.mismatch_type;

  if (loading) {
    return (
      <div
        className="fixed inset-0 flex items-center justify-center z-50"
        style={{ background: "rgba(0, 0, 0, 0.95)" }}
      >
        <div className="bg-slate-800 p-8 rounded-xl">
          <RefreshCw className="animate-spin text-blue-400 w-8 h-8" />
        </div>
      </div>
    );
  }

  return (
    <div
      className="fixed inset-0 flex items-center justify-center z-50 p-4"
      style={{ background: "rgba(0, 0, 0, 0.9)" }}
    >
      <div
        className="rounded-2xl border border-slate-700 w-full max-w-4xl max-h-[90vh] overflow-auto"
        style={{ background: "#0a0f1a" }}
      >
        <div
          className="p-6 border-b border-slate-700 flex justify-between items-center sticky top-0 z-10"
          style={{ background: "#0a0f1a" }}
        >
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Eye className="text-blue-400" /> Transaction Deep Dive
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-800 rounded-lg transition-colors"
          >
            <X className="text-slate-400" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Transaction Header */}
          <div className="flex flex-wrap gap-4 items-center">
            <div className="px-4 py-2 bg-slate-800 rounded-lg">
              <span className="text-slate-400 text-xs">Transaction ID</span>
              <p className="text-white font-mono text-sm">
                {displayId ? `${String(displayId).slice(0, 20)}...` : "N/A"}
              </p>
            </div>
            <div
              className={`px-4 py-2 rounded-lg ${
                displayStatus === "MATCHED"
                  ? "bg-emerald-500/20 text-emerald-400"
                  : displayStatus?.includes("RESOLVED")
                  ? "bg-blue-500/20 text-blue-400"
                  : "bg-red-500/20 text-red-400"
              }`}
            >
              <span className="text-xs opacity-70">Status</span>
              <p className="font-semibold">{displayStatus || "UNKNOWN"}</p>
            </div>
            {displayAmount && (
              <div className="px-4 py-2 bg-slate-800 rounded-lg">
                <span className="text-slate-400 text-xs">Amount</span>
                <p className="text-white font-mono text-sm font-bold">
                  {displayCurrency} {displayAmount?.toLocaleString()}
                </p>
              </div>
            )}
            {displayCountry && (
              <div className="px-4 py-2 bg-slate-800 rounded-lg">
                <span className="text-slate-400 text-xs">Country</span>
                <p className="text-white text-sm">{displayCountry}</p>
              </div>
            )}
            {displayMismatchType && (
              <div className="px-4 py-2 bg-amber-500/20 rounded-lg">
                <span className="text-amber-400 text-xs">Mismatch Type</span>
                <p className="text-amber-300 font-semibold">
                  {displayMismatchType}
                </p>
              </div>
            )}
          </div>

          {/* AI Insight Panel */}
          {ai && (
            <AIInsightPanel
              ai={ai}
              expanded={aiExpanded}
              onToggle={() => setAiExpanded(!aiExpanded)}
            />
          )}

          {/* 3-Way Comparison */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Payment Gateway */}
            <div
              className={`p-4 rounded-xl border ${
                txData?.sources?.payment_gateway
                  ? "bg-blue-500/10 border-blue-500/30"
                  : "bg-slate-800 border-slate-700"
              }`}
            >
              <div className="flex items-center gap-2 mb-4">
                <CreditCard className="text-blue-400" />
                <span className="font-semibold text-white">
                  Payment Gateway
                </span>
              </div>
              {txData?.sources?.payment_gateway ? (
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Amount</span>
                    <span className="text-white font-mono">
                      ${txData.sources.payment_gateway.amount}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Status</span>
                    <span className="text-white">
                      {txData.sources.payment_gateway.status}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Currency</span>
                    <span className="text-white">
                      {txData.sources.payment_gateway.currency}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Channel</span>
                    <span className="text-white">
                      {txData.sources.payment_gateway.channel}
                    </span>
                  </div>
                </div>
              ) : (
                <p className="text-red-400 text-sm">
                  ❌ Missing from this source
                </p>
              )}
            </div>

            {/* Core Banking */}
            <div
              className={`p-4 rounded-xl border ${
                txData?.sources?.core_banking
                  ? "bg-purple-500/10 border-purple-500/30"
                  : "bg-slate-800 border-slate-700"
              }`}
            >
              <div className="flex items-center gap-2 mb-4">
                <Server className="text-purple-400" />
                <span className="font-semibold text-white">Core Banking</span>
              </div>
              {txData?.sources?.core_banking ? (
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Amount</span>
                    <span className="text-white font-mono">
                      ${txData.sources.core_banking.amount}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Status</span>
                    <span className="text-white">
                      {txData.sources.core_banking.status}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Currency</span>
                    <span className="text-white">
                      {txData.sources.core_banking.currency}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Channel</span>
                    <span className="text-white">
                      {txData.sources.core_banking.channel}
                    </span>
                  </div>
                </div>
              ) : (
                <p className="text-red-400 text-sm">
                  ❌ Missing from this source
                </p>
              )}
            </div>

            {/* Mobile Banking */}
            <div
              className={`p-4 rounded-xl border ${
                txData?.sources?.mobile_banking
                  ? "bg-cyan-500/10 border-cyan-500/30"
                  : "bg-slate-800 border-slate-700"
              }`}
            >
              <div className="flex items-center gap-2 mb-4">
                <Smartphone className="text-cyan-400" />
                <span className="font-semibold text-white">Mobile Banking</span>
              </div>
              {txData?.sources?.mobile_banking ? (
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Amount</span>
                    <span className="text-white font-mono">
                      ${txData.sources.mobile_banking.amount}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Status</span>
                    <span className="text-white">
                      {txData.sources.mobile_banking.status}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Currency</span>
                    <span className="text-white">
                      {txData.sources.mobile_banking.currency}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Channel</span>
                    <span className="text-white">
                      {txData.sources.mobile_banking.channel}
                    </span>
                  </div>
                </div>
              ) : (
                <p className="text-red-400 text-sm">
                  ❌ Missing from this source
                </p>
              )}
            </div>
          </div>

          {/* Discrepancies */}
          {txData?.discrepancies?.length > 0 && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4">
              <h3 className="text-red-400 font-semibold mb-3 flex items-center gap-2">
                <AlertTriangle size={18} /> Detected Discrepancies
              </h3>
              <div className="space-y-2">
                {txData.discrepancies.map((d, i) => (
                  <div key={i} className="flex items-center gap-4 text-sm">
                    <span
                      className={`px-2 py-1 rounded text-xs ${
                        d.severity === "high"
                          ? "bg-red-500/20 text-red-400"
                          : d.severity === "medium"
                          ? "bg-amber-500/20 text-amber-400"
                          : "bg-blue-500/20 text-blue-400"
                      }`}
                    >
                      {d.severity.toUpperCase()}
                    </span>
                    <span className="text-slate-400">{d.field}:</span>
                    <span className="text-white font-mono">
                      {Object.entries(d.values)
                        .map(([k, v]) => `${k}=${v}`)
                        .join(" | ")}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// Login removed: UI now renders dashboard without a login gate

// Connection Status Banner Component
const ConnectionBanner = ({
  socketConnected,
  kafkaConnected,
  backendHealth,
}) => {
  if (socketConnected && kafkaConnected) return null;

  let message = "";
  let className = "connection-banner ";

  if (!socketConnected) {
    message = "⚡ Reconnecting to server...";
    className += "disconnected";
  } else if (!kafkaConnected) {
    message = "🔄 Waiting for Kafka connection...";
    className += "connecting";
  }

  return (
    <div className={className}>
      <div className="flex items-center justify-center gap-2">
        <RefreshCw className="animate-spin" size={16} />
        <span>{message}</span>
      </div>
    </div>
  );
};

// System Health Widget
const SystemHealthWidget = ({ health, uptime }) => {
  return (
    <div className="glass-card rounded-xl p-4 border border-slate-700/50">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <Cpu size={16} className="text-cyan-400" />
          System Status
        </h4>
        <span
          className={`text-xs px-2 py-1 rounded-full font-medium ${
            health?.status === "healthy"
              ? "bg-emerald-500/20 text-emerald-400"
              : "bg-amber-500/20 text-amber-400"
          }`}
        >
          {health?.status?.toUpperCase() || "CHECKING"}
        </span>
      </div>

      <div className="space-y-2 text-xs">
        <div className="flex items-center justify-between">
          <span className="text-slate-400 flex items-center gap-1">
            <Database size={12} /> Database
          </span>
          <span
            className={
              health?.database?.connected ? "text-emerald-400" : "text-red-400"
            }
          >
            {health?.database?.connected ? "● Connected" : "● Disconnected"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-slate-400 flex items-center gap-1">
            <HardDrive size={12} /> Kafka
          </span>
          <span
            className={
              health?.kafka?.connected ? "text-emerald-400" : "text-red-400"
            }
          >
            {health?.kafka?.connected ? "● Connected" : "● Disconnected"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-slate-400 flex items-center gap-1">
            <Brain size={12} /> AI Foundry
          </span>
          <span
            className={
              health?.ai_runtime?.configured
                ? "text-emerald-400"
                : "text-amber-400"
            }
          >
            {health?.ai_runtime?.configured ? "● Active" : "● Not Configured"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-slate-400 flex items-center gap-1">
            <Shield size={12} /> Content Safety
          </span>
          <span
            className={
              health?.safety_runtime?.configured
                ? "text-emerald-400"
                : "text-amber-400"
            }
          >
            {health?.safety_runtime?.configured
              ? "● Active"
              : "● Not Configured"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-slate-400 flex items-center gap-1">
            <Clock size={12} /> Uptime
          </span>
          <span className="text-slate-300 font-mono">
            {health?.uptime || "0h 0m"}
          </span>
        </div>
      </div>
    </div>
  );
};

const Dashboard = ({ token, logout }) => {
  const [alerts, setAlerts] = useState([]);
  const [stats, setStats] = useState({
    total_processed: 0,
    total_issues: 0,
    health_score: 100,
    tpm: 0,
    match_rate: 100,
    avg_resolution_time: 0,
    total_matched: 0,
    total_auto_resolved: 0,
  });
  const [chartData, setChartData] = useState([]);
  const [activeTab, setActiveTab] = useState("overview");
  const [riskAmount, setRiskAmount] = useState(0);
  const [heatmapData, setHeatmapData] = useState([]);
  const [geoRiskData, setGeoRiskData] = useState([]);
  const [mismatchTypes, setMismatchTypes] = useState([]);
  const [selectedTx, setSelectedTx] = useState(null);
  const [selectedAlertData, setSelectedAlertData] = useState(null);
  const [aiDrawerAlert, setAiDrawerAlert] = useState(null);
  const [showNotifications, setShowNotifications] = useState(false);
  const [settings, setSettings] = useState({
    auto_mitigation: true,
    risk_threshold: 80,
    sound_alerts: true,
  });
  const [chaosControl, setChaosControl] = useState({
    running: false,
    speed: 1.0,
    chaos_rate: 40,
  });

  // Transaction filter state
  const [txFilter, setTxFilter] = useState("all"); // 'all', 'errors', 'warnings', 'success'

  // Connection status tracking
  const [socketConnected, setSocketConnected] = useState(false);
  const [kafkaConnected, setKafkaConnected] = useState(false);
  const [backendHealth, setBackendHealth] = useState(null);

  const alertSoundEnabled = useRef(true);
  const reconnectAttempts = useRef(0);
  const alertQueue = useRef([]);
  const isProcessingQueue = useRef(false);

  // Process alert queue smoothly - one at a time with delay
  const processAlertQueue = useCallback(() => {
    if (isProcessingQueue.current || alertQueue.current.length === 0) return;

    isProcessingQueue.current = true;

    const processNext = () => {
      if (alertQueue.current.length === 0) {
        isProcessingQueue.current = false;
        return;
      }

      const nextAlert = alertQueue.current.shift();

      setAlerts((prev) => {
        const newAlerts = [nextAlert, ...prev];
        return newAlerts.slice(0, 100);
      });

      if (nextAlert.severity === "error" && nextAlert.amount) {
        setRiskAmount((prev) => prev + nextAlert.amount);
      }

      setChartData((prev) => {
        const now = new Date();
        const timeStr = now.toLocaleTimeString("en-US", {
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        });
        const newData = [
          ...prev,
          {
            time: timeStr,
            amount: nextAlert.amount,
            severity:
              nextAlert.severity === "error"
                ? 100
                : nextAlert.severity === "warning"
                ? 50
                : 10,
          },
        ];
        return newData.slice(-30);
      });

      // Process next item after a delay for smooth animation
      setTimeout(processNext, 300);
    };

    processNext();
  }, []);

  // Fetch chaos producer status (no auth required)
  const fetchChaosStatus = useCallback(async () => {
    try {
      const res = await axios.get(`${SOCKET_URL}/api/chaos/status`);
      setChaosControl(res.data);
    } catch (err) {
      console.error("Failed to fetch chaos status");
    }
  }, []);

  // Toggle chaos producer (no auth required)
  const toggleChaos = async () => {
    try {
      const endpoint = chaosControl.running ? "stop" : "start";
      const res = await axios.post(`${SOCKET_URL}/api/chaos/${endpoint}`);
      setChaosControl(res.data);
    } catch (err) {
      console.error("Failed to toggle chaos");
    }
  };

  // Update chaos speed (no auth required)
  const updateChaosSpeed = async (speed) => {
    try {
      const res = await axios.post(`${SOCKET_URL}/api/chaos/speed`, { speed });
      setChaosControl(res.data);
    } catch (err) {
      console.error("Failed to update speed");
    }
  };

  // Update chaos rate (no auth required)
  const updateChaosRate = async (chaos_rate) => {
    try {
      const res = await axios.post(`${SOCKET_URL}/api/chaos/speed`, {
        chaos_rate,
      });
      setChaosControl(res.data);
    } catch (err) {
      console.error("Failed to update chaos rate");
    }
  };

  const fetchStats = useCallback(async () => {
    try {
      const res = await axios.get(`${SOCKET_URL}/api/stats`);
      setStats(res.data);

      const heatRes = await axios.get(`${SOCKET_URL}/api/heatmap`);
      setHeatmapData(heatRes.data);

      const geoRes = await axios.get(`${SOCKET_URL}/api/geo-risk`);
      setGeoRiskData(geoRes.data);

      const mismatchRes = await axios.get(`${SOCKET_URL}/api/mismatch-types`);
      const mismatchArray = Object.entries(mismatchRes.data).map(
        ([name, value]) => ({
          name,
          value,
        })
      );
      setMismatchTypes(mismatchArray);
    } catch (err) {
      console.error("Failed to fetch stats:", err.message);
    }
  }, []);

  useEffect(() => {
    // Socket connection handlers
    socket.on("connect", () => {
      console.log("✅ Socket connected");
      setSocketConnected(true);
      reconnectAttempts.current = 0;
    });

    socket.on("disconnect", (reason) => {
      console.log("❌ Socket disconnected:", reason);
      setSocketConnected(false);
    });

    socket.on("connect_error", (error) => {
      console.log("⚠️ Connection error:", error.message);
      setSocketConnected(false);
      reconnectAttempts.current += 1;
    });

    socket.on("reconnect", (attemptNumber) => {
      console.log("🔄 Reconnected after", attemptNumber, "attempts");
      setSocketConnected(true);
    });

    socket.on("system_status", (data) => {
      console.log("📡 System status update:", data);
      setKafkaConnected(data.kafka_connected);
    });

    socket.on("new_alert", (data) => {
      // Add to queue for smooth processing
      alertQueue.current.push(data);
      processAlertQueue();

      // Play sound alert for critical issues immediately
      if (data.severity === "error" && data.amount) {
        if (
          data.sound_alert &&
          alertSoundEnabled.current &&
          settings.sound_alerts
        ) {
          playAlertSound();
        }
      }
    });

    // Fetch initial settings
    const fetchSettings = async () => {
      try {
        const res = await axios.get(`${SOCKET_URL}/api/settings`);
        setSettings(res.data);
        alertSoundEnabled.current = res.data.sound_alerts;
      } catch (err) {
        console.error("Failed to fetch settings");
      }
    };

    // Fetch health status
    const fetchHealth = async () => {
      try {
        const res = await axios.get(`${SOCKET_URL}/api/health`);
        setBackendHealth(res.data);
        setKafkaConnected(res.data.kafka?.connected || false);
      } catch (err) {
        console.error("Failed to fetch health");
        setBackendHealth(null);
      }
    };

    fetchStats();
    fetchSettings();
    fetchChaosStatus();
    fetchHealth();

    const interval = setInterval(fetchStats, 3000);
    const chaosInterval = setInterval(fetchChaosStatus, 2000);
    const healthInterval = setInterval(fetchHealth, 5000);

    return () => {
      socket.off("connect");
      socket.off("disconnect");
      socket.off("connect_error");
      socket.off("reconnect");
      socket.off("system_status");
      socket.off("new_alert");
      clearInterval(interval);
      clearInterval(chaosInterval);
      clearInterval(healthInterval);
    };
  }, [fetchStats, fetchChaosStatus, processAlertQueue, settings.sound_alerts]);

  const downloadReport = async () => {
    try {
      const response = await axios.get(`${SOCKET_URL}/api/export`, {
        headers: { Authorization: `Bearer ${token}` },
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", "reconciliation_report.csv");
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Error downloading report:", error);
      alert(
        "Failed to download report. Please ensure the backend is running and transactions exist."
      );
    }
  };

  const handleResolve = async (tx_id, action) => {
    try {
      const response = await axios.post(
        `${SOCKET_URL}/api/resolve`,
        { tx_id, action },
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );

      // Update local state regardless of backend result
      setAlerts((prev) =>
        prev.map((a) =>
          a.id === tx_id
            ? {
                ...a,
                severity: action === "ignore" ? "warning" : "success",
                message:
                  action === "ignore"
                    ? "Ignored by operator"
                    : "Manually Resolved",
              }
            : a
        )
      );

      console.log("Transaction resolved:", response.data);
    } catch (err) {
      console.error("Failed to resolve", err);
      // Still update local state even if backend fails
      setAlerts((prev) =>
        prev.map((a) =>
          a.id === tx_id
            ? { ...a, severity: "success", message: "Resolved (local only)" }
            : a
        )
      );
    }
  };

  const toggleAutoMitigation = async () => {
    const newSetting = !settings.auto_mitigation;
    // Optimistically update UI first
    setSettings((prev) => ({ ...prev, auto_mitigation: newSetting }));
    try {
      await axios.post(`${SOCKET_URL}/api/settings`, {
        auto_mitigation: newSetting,
      });
      console.log("Auto-mitigation toggled to:", newSetting);
    } catch (err) {
      // Revert on error
      setSettings((prev) => ({ ...prev, auto_mitigation: !newSetting }));
      console.error("Failed to update settings:", err);
    }
  };

  const toggleSoundAlerts = async () => {
    const newSetting = !settings.sound_alerts;
    // Optimistically update UI first
    setSettings((prev) => ({ ...prev, sound_alerts: newSetting }));
    alertSoundEnabled.current = newSetting;
    try {
      await axios.post(`${SOCKET_URL}/api/settings`, {
        sound_alerts: newSetting,
      });
      console.log("Sound alerts toggled to:", newSetting);
    } catch (err) {
      // Revert on error
      setSettings((prev) => ({ ...prev, sound_alerts: !newSetting }));
      alertSoundEnabled.current = !newSetting;
      console.error("Failed to update sound settings:", err);
    }
  };

  const getSeverityColor = (severity) => {
    switch (severity) {
      case "error":
        return "text-red-400 bg-red-400/10 border-red-400/20";
      case "warning":
        return "text-amber-400 bg-amber-400/10 border-amber-400/20";
      case "success":
        return "text-emerald-400 bg-emerald-400/10 border-emerald-400/20";
      default:
        return "text-slate-400 bg-slate-400/10 border-slate-400/20";
    }
  };

  // Helper function to get country flag emoji
  const getCountryFlag = (countryCode) => {
    if (!countryCode || countryCode.length !== 2) return "🌍";
    const codePoints = countryCode
      .toUpperCase()
      .split("")
      .map((char) => 127397 + char.charCodeAt(0));
    return String.fromCodePoint(...codePoints);
  };

  return (
    <div className="flex h-screen bg-slate-950 text-slate-200 font-sans overflow-hidden">
      {/* Connection Status Banner */}
      <ConnectionBanner
        socketConnected={socketConnected}
        kafkaConnected={kafkaConnected}
        backendHealth={backendHealth}
      />

      {/* SIDEBAR */}
      <aside className="w-72 bg-gradient-to-b from-slate-900 via-slate-900 to-slate-950 border-r border-slate-800/50 flex flex-col z-20">
        <div className="p-6 flex items-center gap-3 border-b border-slate-800/50">
          <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-900/30 animate-pulse-glow">
            <Shield className="text-white w-5 h-5" />
          </div>
          <div>
            <span className="font-bold text-lg tracking-tight text-white">
              Sentinel
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-400">
                Core
              </span>
            </span>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  socketConnected
                    ? "bg-emerald-400 animate-pulse"
                    : "bg-red-400"
                }`}
              ></span>
              <span className="text-[10px] text-slate-500 uppercase tracking-wider">
                {socketConnected ? "Live" : "Offline"}
              </span>
            </div>
          </div>
        </div>

        <nav className="flex-1 p-4 space-y-1.5">
          <button
            onClick={() => setActiveTab("overview")}
            className={`w-full flex items-center gap-3 px-4 py-3.5 rounded-xl transition-all duration-200 ${
              activeTab === "overview"
                ? "bg-gradient-to-r from-blue-600/20 to-purple-600/20 text-white border border-blue-500/30 shadow-lg shadow-blue-900/20"
                : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
            }`}
          >
            <LayoutDashboard
              size={20}
              className={activeTab === "overview" ? "text-blue-400" : ""}
            />
            <span className="font-medium">Overview</span>
            {activeTab === "overview" && (
              <div className="ml-auto w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse"></div>
            )}
          </button>
          <button
            onClick={() => setActiveTab("ai-insights")}
            className={`w-full flex items-center gap-3 px-4 py-3.5 rounded-xl transition-all duration-200 ${
              activeTab === "ai-insights"
                ? "bg-gradient-to-r from-purple-600/20 to-pink-600/20 text-white border border-purple-500/30 shadow-lg shadow-purple-900/20"
                : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
            }`}
          >
            <Brain
              size={20}
              className={activeTab === "ai-insights" ? "text-purple-400" : ""}
            />
            <span className="font-medium">AI Insights</span>
            {alerts.filter((a) => a.ai).length > 0 && (
              <span className="ml-auto px-2 py-0.5 text-xs font-bold bg-purple-500/20 text-purple-400 rounded-full border border-purple-500/30">
                {alerts.filter((a) => a.ai).length}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab("transactions")}
            className={`w-full flex items-center gap-3 px-4 py-3.5 rounded-xl transition-all duration-200 ${
              activeTab === "transactions"
                ? "bg-gradient-to-r from-blue-600/20 to-purple-600/20 text-white border border-blue-500/30 shadow-lg shadow-blue-900/20"
                : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
            }`}
          >
            <FileText
              size={20}
              className={activeTab === "transactions" ? "text-blue-400" : ""}
            />
            <span className="font-medium">Transactions</span>
            {alerts.filter(
              (a) => a.severity === "error" || a.severity === "warning"
            ).length > 0 && (
              <span className="ml-auto px-2 py-0.5 text-xs font-bold bg-red-500/20 text-red-400 rounded-full border border-red-500/30">
                {
                  alerts.filter(
                    (a) => a.severity === "error" || a.severity === "warning"
                  ).length
                }
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab("settings")}
            className={`w-full flex items-center gap-3 px-4 py-3.5 rounded-xl transition-all duration-200 ${
              activeTab === "settings"
                ? "bg-gradient-to-r from-blue-600/20 to-purple-600/20 text-white border border-blue-500/30 shadow-lg shadow-blue-900/20"
                : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
            }`}
          >
            <Settings
              size={20}
              className={activeTab === "settings" ? "text-blue-400" : ""}
            />
            <span className="font-medium">Settings</span>
          </button>
        </nav>

        <div className="p-4 space-y-3 border-t border-slate-800/50">
          {/* Chaos Producer Quick Control */}
          <div className="glass-card rounded-xl p-4 border border-slate-700/50">
            <div className="flex justify-between items-center mb-3">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Transaction Generator
              </span>
              <span
                className={`text-xs font-bold flex items-center gap-1.5 px-2 py-1 rounded-full ${
                  chaosControl.running
                    ? "text-emerald-400 bg-emerald-500/10 border border-emerald-500/30"
                    : "text-amber-400 bg-amber-500/10 border border-amber-500/30"
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    chaosControl.running
                      ? "bg-emerald-400 animate-pulse"
                      : "bg-amber-400"
                  }`}
                ></span>
                {chaosControl.running ? "RUNNING" : "PAUSED"}
              </span>
            </div>
            <button
              onClick={toggleChaos}
              className={`w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-semibold transition-all duration-200 ${
                chaosControl.running
                  ? "bg-gradient-to-r from-red-500/20 to-orange-500/20 text-red-400 hover:from-red-500/30 hover:to-orange-500/30 border border-red-500/40"
                  : "bg-gradient-to-r from-emerald-500/20 to-teal-500/20 text-emerald-400 hover:from-emerald-500/30 hover:to-teal-500/30 border border-emerald-500/40"
              }`}
            >
              {chaosControl.running ? (
                <>
                  <Pause size={16} /> Pause Generator
                </>
              ) : (
                <>
                  <Play size={16} /> Start Generator
                </>
              )}
            </button>
            <div className="mt-3 flex justify-between text-[11px] text-slate-500">
              <span>
                Speed:{" "}
                <span className="text-slate-300 font-mono">
                  {chaosControl.speed}x
                </span>
              </span>
              <span>
                Chaos:{" "}
                <span className="text-slate-300 font-mono">
                  {chaosControl.chaos_rate}%
                </span>
              </span>
            </div>
          </div>

          {/* System Health Widget */}
          <SystemHealthWidget health={backendHealth} />

          <button
            onClick={logout}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-slate-700/50 text-slate-400 hover:bg-red-900/20 hover:text-red-400 hover:border-red-900/50 transition-all text-sm font-medium"
          >
            <LogOut size={16} />
            <span>Sign Out</span>
          </button>
        </div>
      </aside>

      {/* MAIN CONTENT */}
      <main className="flex-1 flex flex-col overflow-hidden relative">
        <div className="absolute top-0 left-0 w-full h-64 bg-gradient-to-b from-slate-900 to-slate-950 -z-10"></div>

        {/* HEADER */}
        <header className="h-16 border-b border-slate-800/50 flex items-center justify-between px-8 bg-slate-900/30 backdrop-blur-xl z-10">
          <h2 className="text-xl font-bold text-white flex items-center gap-3">
            {activeTab === "overview" && (
              <>
                <div className="p-2 bg-blue-500/10 rounded-lg">
                  <Activity className="text-blue-400" size={20} />
                </div>
                <span>Live Operations Center</span>
              </>
            )}
            {activeTab === "ai-insights" && (
              <>
                <div className="p-2 bg-purple-500/10 rounded-lg">
                  <Brain className="text-purple-400" size={20} />
                </div>
                <span>AI Insights Center</span>
                <Sparkles size={16} className="text-purple-400" />
              </>
            )}
            {activeTab === "transactions" && (
              <>
                <div className="p-2 bg-blue-500/10 rounded-lg">
                  <FileText className="text-blue-400" size={20} />
                </div>
                <span>Transaction Ledger</span>
              </>
            )}
            {activeTab === "settings" && (
              <>
                <div className="p-2 bg-blue-500/10 rounded-lg">
                  <Settings className="text-blue-400" size={20} />
                </div>
                <span>System Configuration</span>
              </>
            )}
          </h2>
          <div className="flex items-center gap-3">
            {/* Connection Status */}
            <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/50 rounded-full border border-slate-700/50">
              {socketConnected ? (
                <Wifi size={14} className="text-emerald-400" />
              ) : (
                <WifiOff size={14} className="text-red-400" />
              )}
              <span className="text-xs font-medium text-slate-300">
                {socketConnected ? "Connected" : "Disconnected"}
              </span>
            </div>

            {/* Auto-pilot status */}
            <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/50 rounded-full border border-slate-700/50">
              <div
                className={`w-2 h-2 rounded-full ${
                  settings.auto_mitigation
                    ? "bg-emerald-400 animate-pulse"
                    : "bg-amber-400"
                }`}
              ></div>
              <span className="text-xs font-medium text-slate-300">
                {settings.auto_mitigation ? "Auto-Pilot ON" : "Manual Mode"}
              </span>
            </div>

            <button
              onClick={toggleSoundAlerts}
              className={`p-2.5 rounded-xl transition-all duration-200 ${
                settings.sound_alerts
                  ? "text-emerald-400 bg-emerald-500/10 border border-emerald-500/30"
                  : "text-slate-500 bg-slate-800/50 border border-slate-700/50"
              }`}
              title={
                settings.sound_alerts
                  ? "Sound alerts enabled"
                  : "Sound alerts disabled"
              }
            >
              {settings.sound_alerts ? (
                <Volume2 size={18} />
              ) : (
                <VolumeX size={18} />
              )}
            </button>

            <div className="relative">
              <button
                onClick={() => setShowNotifications(!showNotifications)}
                className={`p-2.5 transition-colors relative rounded-xl border ${
                  showNotifications
                    ? "text-blue-400 bg-blue-500/10 border-blue-500/30"
                    : "text-slate-400 hover:text-white bg-slate-800/50 border-slate-700/50"
                }`}
                title="View critical alerts"
              >
                <Bell size={18} />
                {alerts.filter((a) => a.severity === "error").length > 0 && (
                  <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 rounded-full border-2 border-slate-900 text-[10px] font-bold flex items-center justify-center text-white">
                    {Math.min(
                      alerts.filter((a) => a.severity === "error").length,
                      9
                    )}
                  </span>
                )}
              </button>

              {/* Notification Dropdown */}
              {showNotifications && (
                <>
                  {/* Click outside to close */}
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setShowNotifications(false)}
                  />
                  <div
                    className="absolute right-0 mt-2 w-80 rounded-xl shadow-2xl z-50 overflow-hidden"
                    style={{
                      background: "#0a0f1a",
                      border: "1px solid #334155",
                    }}
                  >
                    <div
                      className="p-3 flex justify-between items-center"
                      style={{
                        borderBottom: "1px solid #334155",
                        background: "#0d1321",
                      }}
                    >
                      <h4 className="font-semibold text-white flex items-center gap-2">
                        <AlertOctagon size={14} className="text-red-400" />
                        Critical Alerts
                      </h4>
                      <span className="text-xs bg-red-500/20 text-red-400 px-2 py-0.5 rounded-full">
                        {alerts.filter((a) => a.severity === "error").length}
                      </span>
                    </div>
                    <div
                      className="max-h-64 overflow-y-auto"
                      style={{ background: "#0a0f1a" }}
                    >
                      {alerts.filter((a) => a.severity === "error").length ===
                      0 ? (
                        <div className="p-4 text-center text-slate-500">
                          <CheckCircle
                            size={24}
                            className="mx-auto mb-2 opacity-50"
                          />
                          <p className="text-sm">No critical alerts</p>
                        </div>
                      ) : (
                        alerts
                          .filter((a) => a.severity === "error")
                          .slice(0, 5)
                          .map((alert, idx) => (
                            <div
                              key={idx}
                              className="p-3 cursor-pointer transition-colors hover:bg-slate-800"
                              style={{
                                borderBottom: "1px solid #1e293b",
                                background: "#0a0f1a",
                              }}
                              onClick={() => {
                                setShowNotifications(false);
                                setSelectedTx(alert.id);
                                setSelectedAlertData(alert);
                              }}
                            >
                              <p className="text-sm text-white font-medium line-clamp-1">
                                {alert.message}
                              </p>
                              <div className="flex justify-between items-center mt-1">
                                <span className="text-xs text-slate-500">
                                  {alert.timestamp}
                                </span>
                                <span className="text-xs font-mono text-red-400">
                                  {formatINR(alert.amount)}
                                </span>
                              </div>
                            </div>
                          ))
                      )}
                    </div>
                    {alerts.filter((a) => a.severity === "error").length >
                      5 && (
                      <div
                        className="p-2"
                        style={{
                          borderTop: "1px solid #334155",
                          background: "#0d1321",
                        }}
                      >
                        <button
                          onClick={() => {
                            setShowNotifications(false);
                            setActiveTab("transactions");
                          }}
                          className="w-full text-xs text-blue-400 hover:text-blue-300 transition-colors py-1"
                        >
                          View all{" "}
                          {alerts.filter((a) => a.severity === "error").length}{" "}
                          alerts →
                        </button>
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>

            <div className="w-9 h-9 bg-gradient-to-tr from-blue-500 to-purple-600 rounded-xl border-2 border-slate-800 shadow-lg flex items-center justify-center">
              <span className="text-white font-bold text-sm">A</span>
            </div>
          </div>
        </header>

        {/* SCROLLABLE CONTENT AREA */}
        <div className="flex-1 overflow-y-auto p-8 scroll-smooth">
          {/* OVERVIEW TAB */}
          {activeTab === "overview" && (
            <>
              {/* KPI CARDS */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                <div className="stat-card group">
                  <div className="flex justify-between items-start mb-4">
                    <div className="p-3 bg-gradient-to-br from-blue-500/20 to-cyan-500/10 rounded-xl group-hover:scale-110 transition-transform duration-300">
                      <TrendingUp className="text-blue-400 w-6 h-6" />
                    </div>
                    <div className="flex items-center gap-1.5">
                      <ArrowUpRight size={14} className="text-emerald-400" />
                      <span className="text-xs font-bold text-emerald-400 bg-emerald-900/30 px-2.5 py-1 rounded-lg">
                        {stats.match_rate}% Match
                      </span>
                    </div>
                  </div>
                  <h3 className="text-slate-400 text-sm font-medium mb-1">
                    Total Processed
                  </h3>
                  <p className="text-4xl font-bold text-white mb-3 tracking-tight">
                    {stats.total_processed.toLocaleString()}
                  </p>
                  <div className="flex items-center gap-2 text-xs text-slate-500">
                    <span className="px-2 py-1 bg-emerald-500/10 text-emerald-400 rounded-md">
                      {stats.total_matched} matched
                    </span>
                    <span className="px-2 py-1 bg-blue-500/10 text-blue-400 rounded-md">
                      {stats.total_auto_resolved} auto-fixed
                    </span>
                  </div>
                </div>

                <div className="stat-card group">
                  <div className="flex justify-between items-start mb-4">
                    <div className="p-3 bg-gradient-to-br from-red-500/20 to-orange-500/10 rounded-xl group-hover:scale-110 transition-transform duration-300">
                      <AlertOctagon className="text-red-400 w-6 h-6" />
                    </div>
                    <span className="text-xs font-mono text-slate-400 bg-slate-800 px-2.5 py-1 rounded-lg border border-slate-700">
                      Action Req.
                    </span>
                  </div>
                  <h3 className="text-slate-400 text-sm font-medium mb-1">
                    Critical Mismatches
                  </h3>
                  <p
                    className={`text-4xl font-bold mb-3 tracking-tight ${
                      stats.total_issues > 0
                        ? "text-red-400 neon-text-red"
                        : "text-white"
                    }`}
                  >
                    {stats.total_issues}
                  </p>
                  <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-red-500 to-orange-500 rounded-full transition-all duration-500"
                      style={{
                        width: `${Math.min(
                          (stats.total_issues /
                            Math.max(stats.total_processed, 1)) *
                            100 *
                            10,
                          100
                        )}%`,
                      }}
                    ></div>
                  </div>
                </div>

                <div className="stat-card group">
                  <div className="flex justify-between items-start mb-4">
                    <div className="p-3 bg-gradient-to-br from-emerald-500/20 to-teal-500/10 rounded-xl group-hover:scale-110 transition-transform duration-300">
                      <Zap className="text-emerald-400 w-6 h-6" />
                    </div>
                    <span className="text-xs font-mono text-emerald-400 bg-emerald-500/10 px-2.5 py-1 rounded-lg border border-emerald-500/30 animate-pulse">
                      LIVE
                    </span>
                  </div>
                  <h3 className="text-slate-400 text-sm font-medium mb-1">
                    Velocity (TPM)
                  </h3>
                  <p className="text-4xl font-bold text-white mb-3 tracking-tight">
                    {stats.tpm}
                  </p>
                  <div className="flex items-center gap-2 text-xs text-slate-500">
                    <Clock size={12} className="text-slate-400" />
                    <span>
                      Avg resolution:{" "}
                      <span className="text-emerald-400 font-mono">
                        {stats.avg_resolution_time}s
                      </span>
                    </span>
                  </div>
                </div>

                <div className="stat-card group relative overflow-hidden">
                  <div className="absolute top-0 right-0 w-32 h-32 bg-gradient-to-br from-purple-500/10 to-pink-500/10 rounded-full blur-2xl -translate-y-1/2 translate-x-1/2"></div>
                  <div className="relative">
                    <div className="flex justify-between items-start mb-4">
                      <div className="p-3 bg-gradient-to-br from-purple-500/20 to-pink-500/10 rounded-xl group-hover:scale-110 transition-transform duration-300">
                        <Banknote className="text-purple-400 w-6 h-6" />
                      </div>
                      <span className="text-xs font-bold text-red-400 bg-red-500/10 px-2.5 py-1 rounded-lg border border-red-500/30 flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 bg-red-400 rounded-full animate-pulse"></span>
                        LIVE RISK
                      </span>
                    </div>
                    <h3 className="text-slate-400 text-sm font-medium mb-1">
                      Money at Risk
                    </h3>
                    <p className="text-4xl font-bold text-white mb-3 tracking-tight">
                      $
                      {riskAmount.toLocaleString("en-US", {
                        minimumFractionDigits: 0,
                        maximumFractionDigits: 0,
                      })}
                    </p>
                    <p className="text-xs text-slate-500 mb-2">
                      Estimated in USD equivalent
                    </p>
                    <div className="flex items-center gap-2 text-xs">
                      {riskAmount > 0 ? (
                        <span className="text-red-400 flex items-center gap-1">
                          <ArrowUpRight size={12} /> Increasing
                        </span>
                      ) : (
                        <span className="text-emerald-400 flex items-center gap-1">
                          <Target size={12} /> No active risks
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* ROW: Chart + Live Feed - Fixed heights for consistent layout */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* MAIN CHART SECTION - Fixed height */}
                <div
                  className="lg:col-span-2 pro-card p-6"
                  style={{ height: "420px" }}
                >
                  <div className="flex justify-between items-center mb-6">
                    <h3 className="font-bold text-lg text-white flex items-center gap-2">
                      <Activity size={18} className="text-blue-400" />
                      Transaction Velocity & Anomalies
                    </h3>
                    <div className="flex gap-4">
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 bg-blue-500 rounded-full"></span>
                        <span className="text-xs text-slate-400">Volume</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 bg-red-500 rounded-full"></span>
                        <span className="text-xs text-slate-400">
                          Risk Score
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="h-80 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={chartData}>
                        <defs>
                          <linearGradient
                            id="colorAmt"
                            x1="0"
                            y1="0"
                            x2="0"
                            y2="1"
                          >
                            <stop
                              offset="5%"
                              stopColor="#3b82f6"
                              stopOpacity={0.3}
                            />
                            <stop
                              offset="95%"
                              stopColor="#3b82f6"
                              stopOpacity={0}
                            />
                          </linearGradient>
                          <linearGradient
                            id="colorSev"
                            x1="0"
                            y1="0"
                            x2="0"
                            y2="1"
                          >
                            <stop
                              offset="5%"
                              stopColor="#ef4444"
                              stopOpacity={0.3}
                            />
                            <stop
                              offset="95%"
                              stopColor="#ef4444"
                              stopOpacity={0}
                            />
                          </linearGradient>
                        </defs>
                        <CartesianGrid
                          strokeDasharray="3 3"
                          stroke="#1e293b"
                          vertical={false}
                        />
                        <XAxis
                          dataKey="time"
                          stroke="#475569"
                          tick={{ fill: "#64748b", fontSize: 10 }}
                          tickLine={false}
                          axisLine={false}
                          interval="preserveStartEnd"
                        />
                        <YAxis
                          yAxisId="left"
                          stroke="#475569"
                          tick={{ fill: "#64748b", fontSize: 10 }}
                          tickLine={false}
                          axisLine={false}
                        />
                        <YAxis
                          yAxisId="right"
                          orientation="right"
                          stroke="#475569"
                          tick={{ fill: "#64748b", fontSize: 10 }}
                          tickLine={false}
                          axisLine={false}
                          domain={[0, 100]}
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: "#0f172a",
                            border: "1px solid #1e293b",
                            borderRadius: "8px",
                            color: "#fff",
                          }}
                          itemStyle={{ fontSize: "12px" }}
                          labelStyle={{
                            color: "#94a3b8",
                            marginBottom: "4px",
                            fontSize: "10px",
                          }}
                        />
                        <Area
                          yAxisId="left"
                          type="monotone"
                          dataKey="amount"
                          stroke="#3b82f6"
                          strokeWidth={2}
                          fillOpacity={1}
                          fill="url(#colorAmt)"
                          name="Transaction Amount"
                          isAnimationActive={false}
                        />
                        <Area
                          yAxisId="right"
                          type="step"
                          dataKey="severity"
                          stroke="#ef4444"
                          strokeWidth={2}
                          fillOpacity={1}
                          fill="url(#colorSev)"
                          name="Risk Score"
                          isAnimationActive={false}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* LIVE FEED SECTION - Fixed height to match chart */}
                <div
                  className="pro-card flex flex-col overflow-hidden"
                  style={{ height: "420px" }}
                >
                  <div className="p-4 border-b border-slate-700/50 flex justify-between items-center flex-shrink-0">
                    <h3 className="font-bold text-white flex items-center gap-2">
                      <AlertTriangle size={18} className="text-amber-400" />
                      Live Incident Feed
                    </h3>
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-1.5">
                        <span className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse"></span>
                        <span className="text-[10px] text-slate-400">LIVE</span>
                      </div>
                      <span className="text-xs bg-slate-700/50 text-slate-300 px-2.5 py-1 rounded-full">
                        {alerts.length} Events
                      </span>
                    </div>
                  </div>

                  <div className="flex-1 overflow-y-auto p-3 space-y-2 main-scroll">
                    {alerts.length === 0 ? (
                      <div className="h-full flex flex-col items-center justify-center text-slate-500">
                        <CheckCircle size={48} className="mb-3 opacity-50" />
                        <p className="text-lg font-medium">
                          All Systems Nominal
                        </p>
                        <p className="text-sm text-slate-600 mt-1">
                          Waiting for transactions...
                        </p>
                      </div>
                    ) : (
                      alerts.slice(0, 15).map((alert, idx) => (
                        <div
                          key={alert.id || idx}
                          className={`p-3 rounded-lg border animate-fade-in transition-all cursor-pointer hover:brightness-110 ${getSeverityColor(
                            alert.severity
                          )}`}
                          onClick={() => {
                            if (alert.ai) {
                              setAiDrawerAlert(alert);
                            } else {
                              setSelectedTx(alert.id);
                              setSelectedAlertData(alert);
                            }
                          }}
                        >
                          <div className="flex items-center gap-2">
                            {/* Severity Icon */}
                            <div className="flex-shrink-0">
                              {alert.severity === "error" && (
                                <AlertOctagon
                                  size={14}
                                  className="text-red-400"
                                />
                              )}
                              {alert.severity === "warning" && (
                                <AlertTriangle
                                  size={14}
                                  className="text-amber-400"
                                />
                              )}
                              {alert.severity === "success" && (
                                <CheckCircle
                                  size={14}
                                  className="text-emerald-400"
                                />
                              )}
                            </div>

                            {/* Main Content */}
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center justify-between gap-2">
                                <p className="font-medium text-xs text-white truncate">
                                  {alert.message.length > 50
                                    ? alert.message.substring(0, 50) + "..."
                                    : alert.message}
                                </p>
                                <span className="text-[10px] text-slate-500 whitespace-nowrap flex-shrink-0">
                                  {alert.timestamp}
                                </span>
                              </div>

                              {/* Quick Info Row */}
                              <div className="flex items-center gap-2 mt-1">
                                {/* Country Flag */}
                                {alert.country && (
                                  <span
                                    className="text-xs"
                                    title={alert.country}
                                  >
                                    {getCountryFlag(alert.country)}
                                  </span>
                                )}

                                {/* Amount with Currency */}
                                <span className="text-[10px] font-mono text-slate-300">
                                  {formatCurrency(
                                    alert.amount,
                                    alert.currency || "INR"
                                  )}
                                </span>

                                {/* AI Badge */}
                                {alert.ai && (
                                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium bg-blue-500/20 text-blue-400 border border-blue-500/30">
                                    <Brain size={8} />
                                    AI
                                  </span>
                                )}

                                {/* Auto-Fixed Badge */}
                                {alert.message.includes("AUTO-MITIGATED") && (
                                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                                    AUTO
                                  </span>
                                )}

                                {/* Click hint */}
                                <span className="ml-auto text-[9px] text-blue-400 opacity-60">
                                  {alert.ai
                                    ? "Click for AI →"
                                    : "Click to view →"}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>

              {/* HEATMAP SECTION */}
              <div className="pro-card p-6 mt-8">
                <div className="flex justify-between items-center mb-6">
                  <h3 className="font-bold text-lg text-white flex items-center gap-2">
                    <AlertOctagon size={18} className="text-red-400" />
                    Mismatch Heatmap (Day × Hour Matrix)
                  </h3>
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <span className="w-3 h-3 bg-slate-700 rounded"></span> Low
                    <span className="w-3 h-3 bg-amber-500 rounded"></span>{" "}
                    Medium
                    <span className="w-3 h-3 bg-red-500 rounded"></span> High
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <div className="min-w-[800px]">
                    {/* Hour labels */}
                    <div className="flex mb-2 pl-12">
                      {Array.from({ length: 24 }, (_, i) => (
                        <div
                          key={i}
                          className="flex-1 text-center text-[10px] text-slate-500"
                        >
                          {i}:00
                        </div>
                      ))}
                    </div>
                    {/* Heatmap grid */}
                    {heatmapData.length > 0 ? (
                      heatmapData.map((dayData, dayIdx) => (
                        <div key={dayIdx} className="flex items-center mb-1">
                          <div className="w-12 text-xs text-slate-400 font-medium">
                            {dayData.day}
                          </div>
                          <div className="flex-1 flex gap-0.5">
                            {Array.from({ length: 24 }, (_, hour) => {
                              const value = dayData[`h${hour}`] || 0;
                              const intensity = Math.min(value / 10, 1);
                              const bgColor =
                                value === 0
                                  ? "bg-slate-700/50 border border-slate-600/30"
                                  : intensity < 0.3
                                  ? "bg-emerald-500/40 border border-emerald-500/50"
                                  : intensity < 0.6
                                  ? "bg-amber-500/60 border border-amber-500/70"
                                  : "bg-red-500/80 border border-red-500/90";
                              return (
                                <div
                                  key={hour}
                                  className={`flex-1 h-6 rounded-sm ${bgColor} hover:ring-1 hover:ring-white/50 transition-all cursor-pointer flex items-center justify-center`}
                                  title={`${dayData.day} ${hour}:00 - ${value} mismatches`}
                                >
                                  {value > 0 && (
                                    <span className="text-[8px] font-bold text-white">
                                      {value}
                                    </span>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="text-center text-slate-500 py-8">
                        No mismatch data yet. Start the chaos producer to
                        generate transactions.
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* GEO RISK & MISMATCH TYPES ROW */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-8">
                {/* Geographic Risk */}
                <div className="pro-card p-6">
                  <h3 className="font-bold text-lg text-white flex items-center gap-2 mb-4">
                    <Globe size={18} className="text-cyan-400" />
                    Geographic Risk Analysis
                  </h3>
                  <div className="space-y-3 max-h-72 overflow-y-auto main-scroll pr-2">
                    {geoRiskData.slice(0, 10).map((geo, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between p-4 bg-slate-900/50 rounded-xl border border-slate-700/30 hover:border-slate-600/50 transition-colors"
                      >
                        <div className="flex items-center gap-3">
                          <span className="text-2xl">
                            {getCountryFlag(geo.country)}
                          </span>
                          <div>
                            <p className="text-white font-medium">
                              {geo.country}
                            </p>
                            <p className="text-xs text-slate-400">
                              {geo.total} transactions
                            </p>
                          </div>
                        </div>
                        <div className="text-right">
                          <p
                            className={`font-bold text-lg ${
                              geo.risk_rate > 20
                                ? "text-red-400"
                                : geo.risk_rate > 10
                                ? "text-amber-400"
                                : "text-emerald-400"
                            }`}
                          >
                            {geo.risk_rate}%
                          </p>
                          <p className="text-xs text-slate-500">
                            {geo.mismatches} issues
                          </p>
                        </div>
                      </div>
                    ))}
                    {geoRiskData.length === 0 && (
                      <p className="text-center text-slate-500 py-8">
                        Collecting geographic data...
                      </p>
                    )}
                  </div>
                </div>

                {/* Mismatch Types Breakdown */}
                <div className="pro-card p-6">
                  <h3 className="font-bold text-lg text-white flex items-center gap-2 mb-4">
                    <Activity size={18} className="text-purple-400" />
                    Mismatch Type Breakdown
                  </h3>
                  {mismatchTypes.length > 0 ? (
                    <div className="h-64">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={mismatchTypes}
                            cx="50%"
                            cy="50%"
                            innerRadius={50}
                            outerRadius={80}
                            paddingAngle={2}
                            dataKey="value"
                          >
                            {mismatchTypes.map((entry, index) => (
                              <Cell
                                key={`cell-${index}`}
                                fill={MISMATCH_COLORS[entry.name] || "#64748b"}
                              />
                            ))}
                          </Pie>
                          <Tooltip
                            contentStyle={{
                              backgroundColor: "#0f172a",
                              border: "1px solid #1e293b",
                              borderRadius: "8px",
                              color: "#fff",
                            }}
                          />
                          <Legend
                            formatter={(value) => (
                              <span className="text-slate-300 text-xs">
                                {value}
                              </span>
                            )}
                          />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    <div className="h-64 flex items-center justify-center text-slate-500">
                      <p>Collecting mismatch data...</p>
                    </div>
                  )}
                </div>
              </div>

              {/* RECENT TRANSACTIONS TABLE */}
              <div className="mt-8 pro-card overflow-hidden">
                <div className="p-6 border-b border-slate-700/50 flex justify-between items-center">
                  <h3 className="font-bold text-lg text-white flex items-center gap-2">
                    <FileText size={18} className="text-blue-400" />
                    Recent Audit Logs
                  </h3>
                  <div className="flex gap-4">
                    <button
                      onClick={downloadReport}
                      className="text-sm text-emerald-400 hover:text-emerald-300 transition-colors flex items-center gap-2 px-3 py-1.5 rounded-lg border border-emerald-500/30 hover:bg-emerald-500/10"
                    >
                      <FileText size={14} /> Download Report
                    </button>
                    <button
                      onClick={() => setActiveTab("transactions")}
                      className="text-sm text-blue-400 hover:text-blue-300 transition-colors px-3 py-1.5 rounded-lg border border-blue-500/30 hover:bg-blue-500/10"
                    >
                      View All History
                    </button>
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-900/50 text-slate-400 uppercase text-xs font-semibold tracking-wider">
                      <tr>
                        <th className="p-4">Status</th>
                        <th className="p-4">Transaction ID</th>
                        <th className="p-4">Type</th>
                        <th className="p-4">Amount</th>
                        <th className="p-4">AI</th>
                        <th className="p-4">Country</th>
                        <th className="p-4">Timestamp</th>
                        <th className="p-4 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-700/50">
                      {alerts.slice(0, 10).map((alert, idx) => (
                        <tr
                          key={idx}
                          className="hover:bg-slate-700/30 transition-colors cursor-pointer"
                          onClick={() => {
                            setSelectedTx(alert.id);
                            setSelectedAlertData(alert);
                          }}
                        >
                          <td className="p-4">
                            <span
                              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${getSeverityColor(
                                alert.severity
                              )}`}
                            >
                              {alert.severity === "error"
                                ? "CRITICAL"
                                : alert.severity === "warning"
                                ? "WARNING"
                                : "MATCHED"}
                            </span>
                          </td>
                          <td className="p-4 font-mono text-slate-300">
                            {alert.id?.slice(0, 8)}...
                          </td>
                          <td className="p-4 text-slate-300">
                            {alert.type || "Transfer"}
                          </td>
                          <td className="p-4 font-mono font-medium text-white">
                            {formatINR(alert.amount)}
                          </td>
                          <td className="p-4">
                            {alert.ai ? (
                              <div className="flex items-center gap-1.5">
                                {alert.ai.ok ? (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                                    <Brain size={10} />
                                    OK
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-red-500/20 text-red-400 border border-red-500/30">
                                    <AlertTriangle size={10} />
                                    ERR
                                  </span>
                                )}
                                {alert.ai.content_safety?.enabled &&
                                  (alert.ai.content_safety.allowed ? (
                                    <ShieldCheck
                                      size={12}
                                      className="text-emerald-400"
                                    />
                                  ) : (
                                    <ShieldAlert
                                      size={12}
                                      className="text-red-400"
                                    />
                                  ))}
                              </div>
                            ) : (
                              <span className="text-slate-500 text-xs">—</span>
                            )}
                          </td>
                          <td className="p-4 text-slate-300">
                            {getCountryFlag(alert.country)} {alert.country}
                          </td>
                          <td className="p-4 text-slate-400">
                            {alert.timestamp}
                          </td>
                          <td className="p-4 text-right">
                            <button
                              className="text-slate-400 hover:text-white transition-colors"
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedTx(alert.id);
                                setSelectedAlertData(alert);
                              }}
                            >
                              <Eye size={16} />
                            </button>
                          </td>
                        </tr>
                      ))}
                      {alerts.length === 0 && (
                        <tr>
                          <td
                            colSpan="8"
                            className="p-8 text-center text-slate-500"
                          >
                            Waiting for transaction stream...
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}

          {/* Transaction Detail Modal */}
          {selectedTx && (
            <TransactionModal
              txId={selectedTx}
              token={token}
              onClose={() => {
                setSelectedTx(null);
                setSelectedAlertData(null);
              }}
              alertData={selectedAlertData}
            />
          )}

          {/* AI Analysis Drawer */}
          {aiDrawerAlert && (
            <AIDrawer
              alert={aiDrawerAlert}
              onClose={() => setAiDrawerAlert(null)}
              onViewTransaction={(txId, alertData) => {
                setSelectedTx(txId);
                setSelectedAlertData(alertData);
              }}
            />
          )}

          {/* AI INSIGHTS TAB */}
          {activeTab === "ai-insights" && (
            <div className="space-y-6">
              {/* AI Stats Overview */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                <div className="stat-card">
                  <div className="flex items-center justify-between mb-3">
                    <div className="p-3 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/10">
                      <Brain className="text-purple-400 w-6 h-6" />
                    </div>
                    <span className="text-xs font-mono text-purple-400 bg-purple-500/10 px-2 py-1 rounded-lg border border-purple-500/30">
                      AZURE AI
                    </span>
                  </div>
                  <h3 className="text-slate-400 text-sm font-medium mb-1">
                    AI Analyses
                  </h3>
                  <p className="text-4xl font-bold text-white tracking-tight">
                    {alerts.filter((a) => a.ai).length}
                  </p>
                  <p className="text-xs text-slate-500 mt-2">
                    Total insights generated
                  </p>
                </div>

                <div className="stat-card">
                  <div className="flex items-center justify-between mb-3">
                    <div className="p-3 rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-500/10">
                      <ShieldCheck className="text-emerald-400 w-6 h-6" />
                    </div>
                  </div>
                  <h3 className="text-slate-400 text-sm font-medium mb-1">
                    Safe Content
                  </h3>
                  <p className="text-4xl font-bold text-emerald-400 tracking-tight">
                    {
                      alerts.filter(
                        (a) => a.ai?.content_safety?.allowed !== false
                      ).length
                    }
                  </p>
                  <p className="text-xs text-slate-500 mt-2">
                    Passed safety checks
                  </p>
                </div>

                <div className="stat-card">
                  <div className="flex items-center justify-between mb-3">
                    <div className="p-3 rounded-xl bg-gradient-to-br from-red-500/20 to-orange-500/10">
                      <ShieldAlert className="text-red-400 w-6 h-6" />
                    </div>
                  </div>
                  <h3 className="text-slate-400 text-sm font-medium mb-1">
                    Blocked
                  </h3>
                  <p className="text-4xl font-bold text-red-400 tracking-tight">
                    {
                      alerts.filter(
                        (a) => a.ai?.content_safety?.allowed === false
                      ).length
                    }
                  </p>
                  <p className="text-xs text-slate-500 mt-2">
                    Failed safety checks
                  </p>
                </div>

                <div className="stat-card">
                  <div className="flex items-center justify-between mb-3">
                    <div className="p-3 rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-500/10">
                      <Target className="text-blue-400 w-6 h-6" />
                    </div>
                  </div>
                  <h3 className="text-slate-400 text-sm font-medium mb-1">
                    Avg Confidence
                  </h3>
                  <p className="text-4xl font-bold text-blue-400 tracking-tight">
                    {alerts.filter((a) => a.ai?.raw?.confidence).length > 0
                      ? Math.round(
                          (alerts
                            .filter((a) => a.ai?.raw?.confidence)
                            .reduce((sum, a) => sum + a.ai.raw.confidence, 0) /
                            alerts.filter((a) => a.ai?.raw?.confidence)
                              .length) *
                            100
                        )
                      : 0}
                    %
                  </p>
                  <p className="text-xs text-slate-500 mt-2">
                    AI confidence score
                  </p>
                </div>
              </div>

              {/* AI Analysis Feed */}
              <div className="pro-card">
                <div className="p-6 border-b border-slate-700/50 flex justify-between items-center">
                  <h3 className="font-bold text-lg text-white flex items-center gap-3">
                    <Brain className="text-purple-400" />
                    AI Analysis Feed
                    <Sparkles size={16} className="text-purple-400" />
                  </h3>
                  <div className="flex gap-2">
                    <span className="px-3 py-1.5 bg-purple-500/10 text-purple-400 rounded-lg text-xs font-medium border border-purple-500/30">
                      {alerts.filter((a) => a.ai).length} Insights
                    </span>
                  </div>
                </div>

                <div className="divide-y divide-slate-700/30">
                  {alerts.filter((a) => a.ai).length === 0 ? (
                    <div className="p-12 text-center">
                      <Brain
                        size={48}
                        className="text-slate-600 mx-auto mb-4"
                      />
                      <h4 className="text-lg font-medium text-slate-400 mb-2">
                        No AI Insights Yet
                      </h4>
                      <p className="text-sm text-slate-500">
                        AI analysis will appear here as transactions are
                        processed.
                      </p>
                    </div>
                  ) : (
                    alerts
                      .filter((a) => a.ai)
                      .slice(0, 20)
                      .map((alert, idx) => (
                        <div
                          key={idx}
                          className="p-6 hover:bg-slate-800/30 transition-colors cursor-pointer"
                          onClick={() => setAiDrawerAlert(alert)}
                        >
                          <div className="flex gap-5">
                            {/* AI Avatar */}
                            <div className="flex-shrink-0">
                              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shadow-lg shadow-purple-900/20">
                                <Bot size={24} className="text-white" />
                              </div>
                            </div>

                            {/* Content */}
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-3 mb-2">
                                <span className="font-semibold text-white">
                                  AI Analysis
                                </span>
                                <span className="text-xs text-slate-500">
                                  {alert.timestamp}
                                </span>
                                {alert.ai.ok ? (
                                  <span className="px-2 py-0.5 text-[10px] font-medium bg-emerald-500/20 text-emerald-400 rounded-full border border-emerald-500/30">
                                    SUCCESS
                                  </span>
                                ) : (
                                  <span className="px-2 py-0.5 text-[10px] font-medium bg-red-500/20 text-red-400 rounded-full border border-red-500/30">
                                    ERROR
                                  </span>
                                )}
                                {alert.ai.content_safety?.enabled && (
                                  <ContentSafetyBadge
                                    safety={alert.ai.content_safety}
                                  />
                                )}
                              </div>

                              {/* Analysis Text */}
                              <p className="text-sm text-slate-300 leading-relaxed mb-3 line-clamp-3">
                                {alert.ai.analysis}
                              </p>

                              {/* Metadata */}
                              <div className="flex items-center gap-4 text-xs">
                                <span className="text-slate-500">
                                  Transaction:{" "}
                                  <span className="font-mono text-slate-400">
                                    {alert.id?.slice(0, 12)}...
                                  </span>
                                </span>
                                <span className="text-slate-500">
                                  Amount:{" "}
                                  <span className="font-bold text-white">
                                    {formatINR(alert.amount)}
                                  </span>
                                </span>
                                {alert.ai.raw?.severity && (
                                  <span
                                    className={`px-2 py-0.5 rounded font-bold uppercase ${
                                      alert.ai.raw.severity === "critical"
                                        ? "bg-red-500/20 text-red-400"
                                        : alert.ai.raw.severity === "high"
                                        ? "bg-orange-500/20 text-orange-400"
                                        : alert.ai.raw.severity === "medium"
                                        ? "bg-amber-500/20 text-amber-400"
                                        : "bg-emerald-500/20 text-emerald-400"
                                    }`}
                                  >
                                    {alert.ai.raw.severity}
                                  </span>
                                )}
                                {alert.ai.raw?.confidence !== undefined && (
                                  <span className="text-slate-500">
                                    Confidence:{" "}
                                    <span className="font-mono text-blue-400">
                                      {Math.round(
                                        alert.ai.raw.confidence * 100
                                      )}
                                      %
                                    </span>
                                  </span>
                                )}
                                <button
                                  className="ml-auto flex items-center gap-1 text-blue-400 hover:text-blue-300 transition-colors"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setAiDrawerAlert(alert);
                                  }}
                                >
                                  <Maximize2 size={12} />
                                  View Full Analysis
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                      ))
                  )}
                </div>
              </div>
            </div>
          )}

          {/* TRANSACTIONS TAB */}
          {activeTab === "transactions" && (
            <div className="pro-card overflow-hidden">
              <div className="p-6 border-b border-slate-700/50 flex justify-between items-center flex-wrap gap-4">
                <h3 className="font-bold text-lg text-white flex items-center gap-2">
                  <FileText size={18} className="text-blue-400" />
                  Transaction Management
                  <span className="text-xs bg-slate-700 text-slate-300 px-2 py-1 rounded-full">
                    {
                      alerts.filter((a) =>
                        txFilter === "all"
                          ? true
                          : txFilter === "errors"
                          ? a.severity === "error"
                          : txFilter === "warnings"
                          ? a.severity === "warning"
                          : a.severity === "success"
                      ).length
                    }{" "}
                    transactions
                  </span>
                </h3>
                <div className="flex gap-2 flex-wrap">
                  <button
                    onClick={() => setTxFilter("all")}
                    className={`px-4 py-2 rounded-xl text-xs font-medium transition-colors border ${
                      txFilter === "all"
                        ? "bg-blue-500/20 text-blue-400 border-blue-500/30"
                        : "bg-slate-800 hover:bg-slate-700 text-slate-300 border-slate-700"
                    }`}
                  >
                    All
                  </button>
                  <button
                    onClick={() => setTxFilter("errors")}
                    className={`px-4 py-2 rounded-xl text-xs font-medium transition-colors border ${
                      txFilter === "errors"
                        ? "bg-red-500/20 text-red-400 border-red-500/30"
                        : "bg-slate-800 hover:bg-slate-700 text-slate-300 border-slate-700"
                    }`}
                  >
                    Errors (
                    {alerts.filter((a) => a.severity === "error").length})
                  </button>
                  <button
                    onClick={() => setTxFilter("warnings")}
                    className={`px-4 py-2 rounded-xl text-xs font-medium transition-colors border ${
                      txFilter === "warnings"
                        ? "bg-amber-500/20 text-amber-400 border-amber-500/30"
                        : "bg-slate-800 hover:bg-slate-700 text-slate-300 border-slate-700"
                    }`}
                  >
                    Warnings (
                    {alerts.filter((a) => a.severity === "warning").length})
                  </button>
                  <button
                    onClick={() => setTxFilter("success")}
                    className={`px-4 py-2 rounded-xl text-xs font-medium transition-colors border ${
                      txFilter === "success"
                        ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
                        : "bg-slate-800 hover:bg-slate-700 text-slate-300 border-slate-700"
                    }`}
                  >
                    Matched (
                    {alerts.filter((a) => a.severity === "success").length})
                  </button>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-900/50 text-slate-400 uppercase text-xs font-semibold tracking-wider">
                    <tr>
                      <th className="p-4">Status</th>
                      <th className="p-4">Transaction ID</th>
                      <th className="p-4">Details</th>
                      <th className="p-4">Amount</th>
                      <th className="p-4">Country</th>
                      <th className="p-4">Time</th>
                      <th className="p-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/50">
                    {alerts
                      .filter((a) =>
                        txFilter === "all"
                          ? true
                          : txFilter === "errors"
                          ? a.severity === "error"
                          : txFilter === "warnings"
                          ? a.severity === "warning"
                          : a.severity === "success"
                      )
                      .map((alert, idx) => (
                        <tr
                          key={alert.id || idx}
                          className="hover:bg-slate-700/30 transition-colors cursor-pointer"
                          onClick={() => {
                            setSelectedTx(alert.id);
                            setSelectedAlertData(alert);
                          }}
                        >
                          <td className="p-4">
                            <span
                              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${getSeverityColor(
                                alert.severity
                              )}`}
                            >
                              {alert.severity === "error"
                                ? "CRITICAL"
                                : alert.severity === "warning"
                                ? "WARNING"
                                : "MATCHED"}
                            </span>
                          </td>
                          <td className="p-4 font-mono text-slate-300">
                            {alert.id ? `${alert.id.slice(0, 12)}...` : "N/A"}
                          </td>
                          <td className="p-4 text-slate-300 max-w-xs truncate">
                            {alert.message}
                          </td>
                          <td className="p-4 font-mono font-medium text-white">
                            {formatCurrency(
                              alert.amount,
                              alert.currency || "INR"
                            )}
                          </td>
                          <td className="p-4 text-slate-300">
                            {getCountryFlag(alert.country)}{" "}
                            {alert.country || "N/A"}
                          </td>
                          <td className="p-4 text-slate-400">
                            {alert.timestamp}
                          </td>
                          <td className="p-4 text-right">
                            <div
                              className="flex justify-end gap-2"
                              onClick={(e) => e.stopPropagation()}
                            >
                              {alert.ai && (
                                <button
                                  onClick={() => setAiDrawerAlert(alert)}
                                  className="px-3 py-1 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 border border-blue-500/20 rounded text-xs transition-colors flex items-center gap-1"
                                >
                                  <Brain size={12} /> AI
                                </button>
                              )}
                              {alert.severity === "error" && (
                                <>
                                  <button
                                    onClick={() =>
                                      handleResolve(alert.id, "resolve")
                                    }
                                    className="px-3 py-1 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/20 rounded text-xs transition-colors"
                                  >
                                    Resolve
                                  </button>
                                  <button
                                    onClick={() =>
                                      handleResolve(alert.id, "ignore")
                                    }
                                    className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded text-xs transition-colors"
                                  >
                                    Ignore
                                  </button>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    {alerts.filter((a) =>
                      txFilter === "all"
                        ? true
                        : txFilter === "errors"
                        ? a.severity === "error"
                        : txFilter === "warnings"
                        ? a.severity === "warning"
                        : a.severity === "success"
                    ).length === 0 && (
                      <tr>
                        <td
                          colSpan="7"
                          className="p-8 text-center text-slate-500"
                        >
                          No transactions match the selected filter
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* SETTINGS TAB */}
          {activeTab === "settings" && (
            <div className="max-w-3xl mx-auto space-y-6">
              <div className="pro-card p-6">
                <h3 className="font-bold text-lg text-white mb-6 flex items-center gap-2">
                  <Shield className="text-blue-400" /> Mitigation Protocols
                </h3>

                <div className="flex items-center justify-between p-5 bg-slate-900/50 rounded-xl border border-slate-700/50 mb-4 hover:border-slate-600/50 transition-colors">
                  <div>
                    <h4 className="font-medium text-white mb-1">
                      Auto-Mitigation
                    </h4>
                    <p className="text-sm text-slate-400">
                      Automatically attempt to resolve discrepancies using AI
                      confidence scoring and 3-way consensus.
                    </p>
                  </div>
                  <button
                    onClick={toggleAutoMitigation}
                    className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900 ${
                      settings.auto_mitigation ? "bg-blue-600" : "bg-slate-700"
                    }`}
                  >
                    <span
                      className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform shadow-lg ${
                        settings.auto_mitigation
                          ? "translate-x-6"
                          : "translate-x-1"
                      }`}
                    />
                  </button>
                </div>

                <div className="flex items-center justify-between p-5 bg-slate-900/50 rounded-xl border border-slate-700/50 mb-4 hover:border-slate-600/50 transition-colors">
                  <div>
                    <h4 className="font-medium text-white flex items-center gap-2 mb-1">
                      {settings.sound_alerts ? (
                        <Volume2 className="text-emerald-400" />
                      ) : (
                        <VolumeX className="text-slate-500" />
                      )}
                      Sound Alerts
                    </h4>
                    <p className="text-sm text-slate-400">
                      Play audio notification for critical mismatches to get
                      immediate attention.
                    </p>
                  </div>
                  <button
                    onClick={toggleSoundAlerts}
                    className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900 ${
                      settings.sound_alerts ? "bg-emerald-600" : "bg-slate-700"
                    }`}
                  >
                    <span
                      className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform shadow-lg ${
                        settings.sound_alerts
                          ? "translate-x-6"
                          : "translate-x-1"
                      }`}
                    />
                  </button>
                </div>

                <div className="p-5 bg-slate-900/50 rounded-xl border border-slate-700/50">
                  <div className="flex justify-between mb-3">
                    <h4 className="font-medium text-white">Risk Threshold</h4>
                    <span className="text-blue-400 font-mono text-lg">
                      {settings.risk_threshold}%
                    </span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={settings.risk_threshold}
                    onChange={(e) =>
                      setSettings({
                        ...settings,
                        risk_threshold: parseInt(e.target.value),
                      })
                    }
                    className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
                  />
                  <p className="text-sm text-slate-400 mt-3">
                    Transactions with a risk score above this threshold will
                    trigger an immediate halt and operator alert.
                  </p>
                </div>
              </div>

              <div className="pro-card p-6">
                <h3 className="font-bold text-lg text-white mb-6 flex items-center gap-2">
                  <Zap className="text-amber-400" /> Chaos Producer Control
                </h3>

                {/* Start/Stop Button */}
                <div className="flex items-center justify-between p-5 bg-slate-900/50 rounded-xl border border-slate-700/50 mb-4 hover:border-slate-600/50 transition-colors">
                  <div>
                    <h4 className="font-medium text-white flex items-center gap-2 mb-1">
                      {chaosControl.running ? (
                        <span className="w-2.5 h-2.5 bg-emerald-400 rounded-full animate-pulse"></span>
                      ) : (
                        <span className="w-2.5 h-2.5 bg-slate-500 rounded-full"></span>
                      )}
                      Transaction Generator
                    </h4>
                    <p className="text-sm text-slate-400">
                      {chaosControl.running
                        ? "Generating transactions..."
                        : "Paused - Click to resume"}
                    </p>
                  </div>
                  <button
                    onClick={toggleChaos}
                    className={`flex items-center gap-2 px-5 py-2.5 rounded-xl font-medium transition-all ${
                      chaosControl.running
                        ? "bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/50"
                        : "bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 border border-emerald-500/50"
                    }`}
                  >
                    {chaosControl.running ? (
                      <>
                        <Pause size={18} /> Pause
                      </>
                    ) : (
                      <>
                        <Play size={18} /> Start
                      </>
                    )}
                  </button>
                </div>

                {/* Speed Control */}
                <div className="p-5 bg-slate-900/50 rounded-xl border border-slate-700/50 mb-4">
                  <div className="flex justify-between mb-3">
                    <h4 className="font-medium text-white flex items-center gap-2">
                      <Gauge size={16} className="text-blue-400" />
                      Speed (TPS)
                    </h4>
                    <span className="text-blue-400 font-mono text-lg">
                      {chaosControl.speed}x
                    </span>
                  </div>
                  <input
                    type="range"
                    min="0.5"
                    max="10"
                    step="0.5"
                    value={chaosControl.speed}
                    onChange={(e) =>
                      updateChaosSpeed(parseFloat(e.target.value))
                    }
                    className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
                  />
                  <div className="flex justify-between text-xs text-slate-500 mt-2">
                    <span>0.5x (Slow)</span>
                    <span>10x (Fast)</span>
                  </div>
                </div>

                {/* Chaos Rate Control */}
                <div className="p-5 bg-slate-900/50 rounded-xl border border-slate-700/50">
                  <div className="flex justify-between mb-3">
                    <h4 className="font-medium text-white flex items-center gap-2">
                      <AlertTriangle size={16} className="text-amber-400" />
                      Chaos Rate
                    </h4>
                    <span className="text-amber-400 font-mono text-lg">
                      {chaosControl.chaos_rate}%
                    </span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    step="5"
                    value={chaosControl.chaos_rate}
                    onChange={(e) => updateChaosRate(parseInt(e.target.value))}
                    className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-amber-500"
                  />
                  <div className="flex justify-between text-xs text-slate-500 mt-2">
                    <span>0% (All clean)</span>
                    <span>100% (All errors)</span>
                  </div>
                </div>
              </div>

              <div className="pro-card p-6">
                <h3 className="font-bold text-lg text-white mb-6 flex items-center gap-2">
                  <Globe className="text-cyan-400" /> 3-Way Reconciliation
                  Sources
                </h3>
                <div className="space-y-3">
                  <div className="flex items-center justify-between p-4 bg-slate-900/50 rounded-xl border border-emerald-500/30 hover:border-emerald-500/50 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-blue-500/20">
                        <CreditCard className="text-blue-400" />
                      </div>
                      <div>
                        <p className="text-white font-medium">
                          Payment Gateway
                        </p>
                        <p className="text-xs text-slate-400">
                          Topic: pg-transactions
                        </p>
                      </div>
                    </div>
                    <span className="text-emerald-400 text-sm font-medium flex items-center gap-1.5">
                      <span className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse"></span>
                      Connected
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-4 bg-slate-900/50 rounded-xl border border-emerald-500/30 hover:border-emerald-500/50 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-purple-500/20">
                        <Server className="text-purple-400" />
                      </div>
                      <div>
                        <p className="text-white font-medium">
                          Core Banking System
                        </p>
                        <p className="text-xs text-slate-400">
                          Topic: cbs-transactions
                        </p>
                      </div>
                    </div>
                    <span className="text-emerald-400 text-sm font-medium flex items-center gap-1.5">
                      <span className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse"></span>
                      Connected
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-4 bg-slate-900/50 rounded-xl border border-emerald-500/30 hover:border-emerald-500/50 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-cyan-500/20">
                        <Smartphone className="text-cyan-400" />
                      </div>
                      <div>
                        <p className="text-white font-medium">
                          Mobile Banking App
                        </p>
                        <p className="text-xs text-slate-400">
                          Topic: mobile-transactions
                        </p>
                      </div>
                    </div>
                    <span className="text-emerald-400 text-sm font-medium flex items-center gap-1.5">
                      <span className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse"></span>
                      Connected
                    </span>
                  </div>
                </div>
              </div>

              <div className="pro-card p-6">
                <h3 className="font-bold text-lg text-white mb-6 flex items-center gap-2">
                  <RefreshCw className="text-amber-400" /> System Maintenance
                </h3>
                <div className="space-y-3">
                  <button
                    onClick={() => {
                      if (
                        window.confirm(
                          "Clear all cached transactions? This will reset the dashboard view."
                        )
                      ) {
                        setAlerts([]);
                        setChartData([]);
                        setHeatmapData([]);
                        setMismatchTypes([]);
                        setRiskAmount(0);
                      }
                    }}
                    className="w-full p-4 bg-slate-900/50 hover:bg-slate-800 border border-slate-700/50 hover:border-slate-600 rounded-xl text-left flex items-center justify-between group transition-all"
                  >
                    <span className="text-slate-300 font-medium">
                      Clear Transaction Cache
                    </span>
                    <LogOut
                      size={18}
                      className="text-slate-500 group-hover:text-white transition-colors"
                    />
                  </button>
                  <button
                    onClick={downloadReport}
                    className="w-full p-4 bg-slate-900/50 hover:bg-slate-800 border border-slate-700/50 hover:border-slate-600 rounded-xl text-left flex items-center justify-between group transition-all"
                  >
                    <span className="text-slate-300 font-medium">
                      Export Reconciliation Report
                    </span>
                    <FileText
                      size={18}
                      className="text-slate-500 group-hover:text-white transition-colors"
                    />
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
};

function App() {
  const [token, setToken] = useState(localStorage.getItem("token"));

  useEffect(() => {
    const link = document.createElement("link");
    link.href =
      "https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css";
    link.rel = "stylesheet";
    document.head.appendChild(link);

    // Auto-login in local/dev environment so dashboard can fetch protected endpoints
    // Uses default credentials from backend for convenience during development.
    (async function tryAutoLogin() {
      if (token) return;
      try {
        const res = await axios.post(`${SOCKET_URL}/api/login`, {
          username: "admin",
          password: "securePass123!",
        });
        if (res?.data?.token) {
          localStorage.setItem("token", res.data.token);
          setToken(res.data.token);
          console.log("[Auto-Login] token stored");
        }
      } catch (err) {
        console.warn(
          "Auto-login failed (backend may be offline):",
          err.message || err
        );
      }
    })();
  }, [token]);

  return (
    <Dashboard
      token={token}
      logout={() => {
        setToken(null);
        localStorage.removeItem("token");
      }}
    />
  );
}

export default App;
