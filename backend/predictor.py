"""
Predictive Analytics Engine
============================
Real-time prediction of transaction volumes, error rates, and anomaly trends.

Hackathon Feature: Uses exponential moving averages (EMA) and simple trend analysis
to predict future transaction patterns and proactively alert on potential issues.

Key Features:
- Transaction volume forecasting
- Error rate prediction
- Anomaly trend detection
- Peak hour analysis
- Capacity planning suggestions
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import time
import threading
import math
import logging

logger = logging.getLogger(__name__)


@dataclass
class TimeSeriesPoint:
    """A single point in a time series."""
    timestamp: float
    value: float
    label: Optional[str] = None


@dataclass
class Prediction:
    """A prediction with confidence interval."""
    predicted_value: float
    confidence: float
    lower_bound: float
    upper_bound: float
    horizon_minutes: int
    prediction_time: float
    trend: str  # 'rising', 'falling', 'stable'
    
    def to_dict(self) -> Dict:
        return {
            "predicted_value": round(self.predicted_value, 2),
            "confidence": round(self.confidence, 2),
            "lower_bound": round(self.lower_bound, 2),
            "upper_bound": round(self.upper_bound, 2),
            "horizon_minutes": self.horizon_minutes,
            "prediction_time": self.prediction_time,
            "trend": self.trend
        }


class ExponentialMovingAverage:
    """EMA calculator with configurable smoothing factor."""
    
    def __init__(self, alpha: float = 0.3):
        self.alpha = alpha
        self.value: Optional[float] = None
        
    def update(self, new_value: float) -> float:
        if self.value is None:
            self.value = new_value
        else:
            self.value = self.alpha * new_value + (1 - self.alpha) * self.value
        return self.value
    
    def get(self) -> Optional[float]:
        return self.value
    
    def reset(self):
        self.value = None


class TrendDetector:
    """Detects trends in time series data."""
    
    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self.values: deque = deque(maxlen=window_size)
        
    def add(self, value: float):
        self.values.append(value)
        
    def get_trend(self) -> Tuple[str, float]:
        """Returns trend direction and slope."""
        if len(self.values) < 3:
            return "stable", 0.0
        
        # Simple linear regression
        n = len(self.values)
        x_mean = (n - 1) / 2
        y_mean = sum(self.values) / n
        
        numerator = sum((i - x_mean) * (self.values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return "stable", 0.0
        
        slope = numerator / denominator
        
        # Normalize slope as percentage of mean
        normalized_slope = slope / max(y_mean, 1) * 100
        
        if normalized_slope > 5:
            return "rising", normalized_slope
        elif normalized_slope < -5:
            return "falling", normalized_slope
        else:
            return "stable", normalized_slope


class PredictiveEngine:
    """
    Main predictive analytics engine.
    
    Tracks and predicts:
    - Transaction volume per minute (TPM)
    - Error rate (errors per 100 transactions)
    - Average transaction amount
    - System load indicators
    """
    
    def __init__(self, history_window_minutes: int = 60):
        self.history_window = history_window_minutes * 60  # Convert to seconds
        
        # Time series data
        self.tpm_history: deque = deque(maxlen=history_window_minutes)
        self.error_rate_history: deque = deque(maxlen=history_window_minutes)
        self.amount_history: deque = deque(maxlen=history_window_minutes)
        
        # EMA calculators
        self.tpm_ema = ExponentialMovingAverage(alpha=0.3)
        self.error_ema = ExponentialMovingAverage(alpha=0.2)
        self.amount_ema = ExponentialMovingAverage(alpha=0.3)
        
        # Trend detectors
        self.tpm_trend = TrendDetector(window_size=10)
        self.error_trend = TrendDetector(window_size=10)
        
        # Current minute aggregations
        self.current_minute_start: float = time.time()
        self.current_minute_txns: int = 0
        self.current_minute_errors: int = 0
        self.current_minute_total_amount: float = 0.0
        
        # Historical patterns (hour of day -> average TPM)
        self.hourly_patterns: Dict[int, List[float]] = {h: [] for h in range(24)}
        
        # Predictions
        self.last_predictions: Dict[str, Prediction] = {}
        
        self.lock = threading.RLock()
        
    def record_transaction(self, amount: float, is_error: bool = False, 
                          is_mismatch: bool = False, timestamp: float = None):
        """Record a transaction for analytics."""
        if timestamp is None:
            timestamp = time.time()
            
        with self.lock:
            # Check if we need to roll over to a new minute
            if timestamp - self.current_minute_start >= 60:
                self._finalize_minute()
                self.current_minute_start = timestamp
            
            self.current_minute_txns += 1
            self.current_minute_total_amount += amount
            
            if is_error or is_mismatch:
                self.current_minute_errors += 1
    
    def _finalize_minute(self):
        """Finalize the current minute's data and update predictions."""
        if self.current_minute_txns == 0:
            return
        
        tpm = self.current_minute_txns
        error_rate = (self.current_minute_errors / self.current_minute_txns) * 100
        avg_amount = self.current_minute_total_amount / self.current_minute_txns
        
        # Add to history
        self.tpm_history.append(TimeSeriesPoint(
            timestamp=self.current_minute_start,
            value=tpm
        ))
        self.error_rate_history.append(TimeSeriesPoint(
            timestamp=self.current_minute_start,
            value=error_rate
        ))
        self.amount_history.append(TimeSeriesPoint(
            timestamp=self.current_minute_start,
            value=avg_amount
        ))
        
        # Update EMAs
        self.tpm_ema.update(tpm)
        self.error_ema.update(error_rate)
        self.amount_ema.update(avg_amount)
        
        # Update trends
        self.tpm_trend.add(tpm)
        self.error_trend.add(error_rate)
        
        # Store hourly pattern
        hour = datetime.fromtimestamp(self.current_minute_start).hour
        self.hourly_patterns[hour].append(tpm)
        if len(self.hourly_patterns[hour]) > 60:  # Keep last 60 samples per hour
            self.hourly_patterns[hour] = self.hourly_patterns[hour][-60:]
        
        # Reset current minute
        self.current_minute_txns = 0
        self.current_minute_errors = 0
        self.current_minute_total_amount = 0.0
        
        # Update predictions
        self._generate_predictions()
    
    def _generate_predictions(self):
        """Generate predictions for the next 5, 15, and 30 minutes."""
        for horizon in [5, 15, 30]:
            # TPM prediction
            self.last_predictions[f'tpm_{horizon}m'] = self._predict_tpm(horizon)
            
            # Error rate prediction
            self.last_predictions[f'error_{horizon}m'] = self._predict_error_rate(horizon)
    
    def _predict_tpm(self, horizon_minutes: int) -> Prediction:
        """Predict TPM for given horizon."""
        current_ema = self.tpm_ema.get() or 0
        trend, slope = self.tpm_trend.get_trend()
        
        # Simple linear projection
        projected = current_ema + (slope / 100 * current_ema * horizon_minutes / 5)
        projected = max(0, projected)  # Can't be negative
        
        # Confidence based on data amount and trend stability
        data_confidence = min(1.0, len(self.tpm_history) / 30)
        trend_confidence = 1.0 - min(1.0, abs(slope) / 50)
        confidence = (data_confidence + trend_confidence) / 2
        
        # Bounds based on historical variance
        if len(self.tpm_history) > 5:
            values = [p.value for p in self.tpm_history]
            std_dev = self._std_dev(values)
            margin = std_dev * (1 + horizon_minutes / 30)
        else:
            margin = projected * 0.3
        
        return Prediction(
            predicted_value=projected,
            confidence=confidence,
            lower_bound=max(0, projected - margin),
            upper_bound=projected + margin,
            horizon_minutes=horizon_minutes,
            prediction_time=time.time(),
            trend=trend
        )
    
    def _predict_error_rate(self, horizon_minutes: int) -> Prediction:
        """Predict error rate for given horizon."""
        current_ema = self.error_ema.get() or 0
        trend, slope = self.error_trend.get_trend()
        
        # Project the error rate
        projected = current_ema + (slope / 100 * current_ema * horizon_minutes / 5)
        projected = max(0, min(100, projected))  # Clamp to 0-100%
        
        # Calculate confidence
        data_confidence = min(1.0, len(self.error_rate_history) / 30)
        confidence = data_confidence * 0.8  # Error prediction is less reliable
        
        # Calculate bounds
        if len(self.error_rate_history) > 5:
            values = [p.value for p in self.error_rate_history]
            std_dev = self._std_dev(values)
            margin = std_dev * 1.5
        else:
            margin = max(projected * 0.5, 5)
        
        return Prediction(
            predicted_value=projected,
            confidence=confidence,
            lower_bound=max(0, projected - margin),
            upper_bound=min(100, projected + margin),
            horizon_minutes=horizon_minutes,
            prediction_time=time.time(),
            trend=trend
        )
    
    def _std_dev(self, values: List[float]) -> float:
        """Calculate standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return math.sqrt(variance)
    
    def get_predictions(self) -> Dict:
        """Get all current predictions."""
        with self.lock:
            # Force prediction update if we have pending data
            if self.current_minute_txns > 0:
                self._finalize_minute()
            
            return {
                'tpm': {
                    '5m': self.last_predictions.get('tpm_5m', self._empty_prediction(5)).to_dict(),
                    '15m': self.last_predictions.get('tpm_15m', self._empty_prediction(15)).to_dict(),
                    '30m': self.last_predictions.get('tpm_30m', self._empty_prediction(30)).to_dict(),
                },
                'error_rate': {
                    '5m': self.last_predictions.get('error_5m', self._empty_prediction(5)).to_dict(),
                    '15m': self.last_predictions.get('error_15m', self._empty_prediction(15)).to_dict(),
                    '30m': self.last_predictions.get('error_30m', self._empty_prediction(30)).to_dict(),
                },
                'current': {
                    'tpm_ema': round(self.tpm_ema.get() or 0, 2),
                    'error_ema': round(self.error_ema.get() or 0, 2),
                    'amount_ema': round(self.amount_ema.get() or 0, 2),
                    'tpm_trend': self.tpm_trend.get_trend()[0],
                    'error_trend': self.error_trend.get_trend()[0],
                },
                'history': {
                    'tpm': [{'t': p.timestamp, 'v': p.value} for p in list(self.tpm_history)[-30:]],
                    'error': [{'t': p.timestamp, 'v': p.value} for p in list(self.error_rate_history)[-30:]],
                }
            }
    
    def _empty_prediction(self, horizon: int) -> Prediction:
        return Prediction(
            predicted_value=0,
            confidence=0,
            lower_bound=0,
            upper_bound=0,
            horizon_minutes=horizon,
            prediction_time=time.time(),
            trend="stable"
        )
    
    def get_insights(self) -> Dict:
        """Get actionable insights based on predictions."""
        insights = []
        
        with self.lock:
            # Check TPM trends
            tpm_pred_5m = self.last_predictions.get('tpm_5m')
            if tpm_pred_5m:
                if tpm_pred_5m.trend == "rising" and tpm_pred_5m.predicted_value > (self.tpm_ema.get() or 0) * 1.5:
                    insights.append({
                        "type": "warning",
                        "category": "capacity",
                        "message": "Transaction volume expected to increase significantly",
                        "recommendation": "Consider scaling resources proactively"
                    })
            
            # Check error trends
            error_pred_5m = self.last_predictions.get('error_5m')
            if error_pred_5m:
                if error_pred_5m.trend == "rising" and error_pred_5m.predicted_value > 10:
                    insights.append({
                        "type": "critical",
                        "category": "reliability",
                        "message": f"Error rate trending up - predicted {error_pred_5m.predicted_value:.1f}% in 5 minutes",
                        "recommendation": "Investigate system health and recent deployments"
                    })
            
            # Check for stable but high error rate
            error_ema = self.error_ema.get() or 0
            if error_ema > 15:
                insights.append({
                    "type": "critical",
                    "category": "reliability",
                    "message": f"Sustained high error rate: {error_ema:.1f}%",
                    "recommendation": "Immediate investigation required"
                })
            
            # Hour-based pattern matching
            current_hour = datetime.now().hour
            if self.hourly_patterns[current_hour]:
                avg_for_hour = sum(self.hourly_patterns[current_hour]) / len(self.hourly_patterns[current_hour])
                current_tpm = self.tpm_ema.get() or 0
                
                if current_tpm > avg_for_hour * 1.5:
                    insights.append({
                        "type": "info",
                        "category": "pattern",
                        "message": f"Volume unusually high for this time of day ({current_tpm:.0f} vs avg {avg_for_hour:.0f})",
                        "recommendation": "Monitor for potential issues or promotional events"
                    })
        
        return {
            "insights": insights,
            "generated_at": time.time()
        }
    
    def get_forecast_chart_data(self) -> Dict:
        """Get data formatted for forecast visualization."""
        with self.lock:
            # Historical data
            historical = []
            for point in list(self.tpm_history)[-30:]:
                historical.append({
                    "time": datetime.fromtimestamp(point.timestamp).strftime("%H:%M"),
                    "actual": point.value,
                    "type": "actual"
                })
            
            # Add predictions
            tpm_pred_5m = self.last_predictions.get('tpm_5m')
            tpm_pred_15m = self.last_predictions.get('tpm_15m')
            
            predictions = []
            if tpm_pred_5m:
                future_time = datetime.fromtimestamp(time.time() + 300)
                predictions.append({
                    "time": future_time.strftime("%H:%M"),
                    "predicted": tpm_pred_5m.predicted_value,
                    "lower": tpm_pred_5m.lower_bound,
                    "upper": tpm_pred_5m.upper_bound,
                    "type": "prediction"
                })
            
            if tpm_pred_15m:
                future_time = datetime.fromtimestamp(time.time() + 900)
                predictions.append({
                    "time": future_time.strftime("%H:%M"),
                    "predicted": tpm_pred_15m.predicted_value,
                    "lower": tpm_pred_15m.lower_bound,
                    "upper": tpm_pred_15m.upper_bound,
                    "type": "prediction"
                })
            
            return {
                "historical": historical,
                "predictions": predictions
            }


# Global instance
predictor = PredictiveEngine()
