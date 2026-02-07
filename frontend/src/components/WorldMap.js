import React, { useEffect, useRef, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

// City coordinates for all countries in COUNTRY_CONFIG
const CITY_COORDS = {
  // India
  'Mumbai': [19.076, 72.8777],
  'Delhi': [28.6139, 77.209],
  'Bangalore': [12.9716, 77.5946],
  'Chennai': [13.0827, 80.2707],
  'Kolkata': [22.5726, 88.3639],
  'Hyderabad': [17.385, 78.4867],
  'Pune': [18.5204, 73.8567],
  'Ahmedabad': [23.0225, 72.5714],
  'Jaipur': [26.9124, 75.7873],
  'Lucknow': [26.8467, 80.9462],
  
  // USA
  'New York': [40.7128, -74.006],
  'Los Angeles': [34.0522, -118.2437],
  'Chicago': [41.8781, -87.6298],
  'Houston': [29.7604, -95.3698],
  'Phoenix': [33.4484, -112.074],
  'Philadelphia': [39.9526, -75.1652],
  'San Antonio': [29.4241, -98.4936],
  'San Diego': [32.7157, -117.1611],
  
  // UK
  'London': [51.5074, -0.1278],
  'Manchester': [53.4808, -2.2426],
  'Birmingham': [52.4862, -1.8904],
  'Leeds': [53.8008, -1.5491],
  'Glasgow': [55.8642, -4.2518],
  'Liverpool': [53.4084, -2.9916],
  'Edinburgh': [55.9533, -3.1883],
  'Bristol': [51.4545, -2.5879],
  
  // Germany
  'Berlin': [52.52, 13.405],
  'Munich': [48.1351, 11.582],
  'Frankfurt': [50.1109, 8.6821],
  'Hamburg': [53.5511, 9.9937],
  'Cologne': [50.9375, 6.9603],
  'Stuttgart': [48.7758, 9.1829],
  'Düsseldorf': [51.2277, 6.7735],
  'Leipzig': [51.3397, 12.3731],
  
  // Singapore
  'Singapore Central': [1.3521, 103.8198],
  'Jurong': [1.3329, 103.7436],
  'Woodlands': [1.4382, 103.7891],
  'Tampines': [1.3496, 103.9568],
  'Bedok': [1.3236, 103.9273],
  'Ang Mo Kio': [1.3691, 103.8454],
  'Clementi': [1.3162, 103.7649],
  
  // UAE
  'Dubai': [25.2048, 55.2708],
  'Abu Dhabi': [24.4539, 54.3773],
  'Sharjah': [25.3463, 55.4209],
  'Ajman': [25.4052, 55.5136],
  'Ras Al Khaimah': [25.7895, 55.9432],
  'Fujairah': [25.1288, 56.3265],
  
  // Australia
  'Sydney': [-33.8688, 151.2093],
  'Melbourne': [-37.8136, 144.9631],
  'Brisbane': [-27.4698, 153.0251],
  'Perth': [-31.9505, 115.8605],
  'Adelaide': [-34.9285, 138.6007],
  'Gold Coast': [-28.0167, 153.4],
  'Canberra': [-35.2809, 149.13],
};

// Country center coordinates for fallback
const COUNTRY_CENTERS = {
  'IN': [20.5937, 78.9629],
  'US': [37.0902, -95.7129],
  'GB': [55.3781, -3.436],
  'DE': [51.1657, 10.4515],
  'SG': [1.3521, 103.8198],
  'AE': [23.4241, 53.8478],
  'AU': [-25.2744, 133.7751],
};

// Animated marker component
const AnimatedMarker = ({ transaction, onClick }) => {
  const [opacity, setOpacity] = useState(1);
  const [radius, setRadius] = useState(15);
  
  useEffect(() => {
    // Pulse animation
    const pulseInterval = setInterval(() => {
      setRadius(prev => prev === 15 ? 20 : 15);
    }, 500);
    
    // Fade out over time
    const fadeTimeout = setTimeout(() => {
      const fadeInterval = setInterval(() => {
        setOpacity(prev => {
          if (prev <= 0.1) {
            clearInterval(fadeInterval);
            return 0;
          }
          return prev - 0.05;
        });
      }, 200);
    }, 5000);
    
    return () => {
      clearInterval(pulseInterval);
      clearTimeout(fadeTimeout);
    };
  }, []);

  const coords = CITY_COORDS[transaction.city] || COUNTRY_CENTERS[transaction.country] || [0, 0];
  
  // Color based on status
  const getColor = () => {
    if (transaction.severity === 'error' || transaction.status === 'FAILED') return '#ef4444';
    if (transaction.severity === 'warning') return '#f59e0b';
    if (transaction.mismatch_type && transaction.mismatch_type !== 'none') return '#f59e0b';
    return '#22c55e';
  };

  if (opacity <= 0) return null;

  return (
    <CircleMarker
      center={coords}
      radius={radius}
      fillColor={getColor()}
      fillOpacity={opacity * 0.7}
      color={getColor()}
      weight={2}
      opacity={opacity}
      eventHandlers={{
        click: () => onClick && onClick(transaction)
      }}
    >
      <Popup>
        <div className="text-sm">
          <div className="font-bold text-gray-900">
            {transaction.currency} {transaction.amount?.toLocaleString()}
          </div>
          <div className="text-gray-600">{transaction.city}, {transaction.country}</div>
          {transaction.bank && <div className="text-gray-500 text-xs">{transaction.bank}</div>}
          {transaction.mismatch_type && transaction.mismatch_type !== 'none' && (
            <div className="text-red-600 font-medium mt-1">{transaction.mismatch_type}</div>
          )}
        </div>
      </Popup>
    </CircleMarker>
  );
};

// Auto-fit map to show all markers
const MapController = ({ transactions }) => {
  const map = useMap();
  
  useEffect(() => {
    if (transactions.length > 0) {
      const bounds = transactions
        .filter(t => CITY_COORDS[t.city] || COUNTRY_CENTERS[t.country])
        .map(t => CITY_COORDS[t.city] || COUNTRY_CENTERS[t.country]);
      
      if (bounds.length > 1) {
        // Only fit bounds if we have multiple transactions
        // map.fitBounds(bounds, { padding: [50, 50] });
      }
    }
  }, [transactions, map]);
  
  return null;
};

// Heat overlay for high-risk regions
const RiskHeatOverlay = ({ riskData }) => {
  const map = useMap();
  
  useEffect(() => {
    // Could add heatmap.js integration here for more sophisticated heat maps
  }, [riskData, map]);
  
  return null;
};

const WorldMap = ({ transactions = [], riskData = {}, onTransactionClick, height = '400px' }) => {
  const [recentTxns, setRecentTxns] = useState([]);
  const maxMarkers = 50; // Limit markers for performance
  
  useEffect(() => {
    if (transactions.length > 0) {
      setRecentTxns(prev => {
        const newTxns = [...transactions, ...prev];
        // Keep only recent unique transactions
        const unique = newTxns.reduce((acc, txn) => {
          if (!acc.find(t => t.id === txn.id || t.tx_id === txn.tx_id)) {
            acc.push(txn);
          }
          return acc;
        }, []);
        return unique.slice(0, maxMarkers);
      });
    }
  }, [transactions]);

  // Clear old transactions periodically
  useEffect(() => {
    const cleanupInterval = setInterval(() => {
      setRecentTxns(prev => prev.slice(0, Math.max(10, prev.length - 5)));
    }, 10000);
    
    return () => clearInterval(cleanupInterval);
  }, []);

  return (
    <div style={{ height, width: '100%' }} className="rounded-xl overflow-hidden relative">
      <MapContainer
        center={[20, 0]}
        zoom={2}
        style={{ height: '100%', width: '100%' }}
        className="bg-slate-900"
        zoomControl={false}
        attributionControl={false}
      >
        {/* Dark theme tile layer */}
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
        />
        
        <MapController transactions={recentTxns} />
        <RiskHeatOverlay riskData={riskData} />
        
        {/* Transaction markers */}
        {recentTxns.map((txn, idx) => (
          <AnimatedMarker
            key={txn.id || txn.tx_id || idx}
            transaction={txn}
            onClick={onTransactionClick}
          />
        ))}
        
        {/* Static city markers for context */}
        {Object.entries(CITY_COORDS).map(([city, coords]) => (
          <CircleMarker
            key={city}
            center={coords}
            radius={3}
            fillColor="#475569"
            fillOpacity={0.5}
            color="transparent"
            weight={0}
          >
            <Popup>
              <span className="text-sm font-medium">{city}</span>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
      
      {/* Legend overlay */}
      <div className="absolute bottom-4 right-4 bg-slate-900/90 backdrop-blur p-3 rounded-lg border border-slate-700 z-[1000]">
        <div className="text-xs font-medium text-slate-300 mb-2">Transaction Status</div>
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-green-500"></span>
            <span className="text-xs text-slate-400">Verified</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-amber-500"></span>
            <span className="text-xs text-slate-400">Mismatch</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-red-500"></span>
            <span className="text-xs text-slate-400">Error/Fraud</span>
          </div>
        </div>
      </div>
      
      {/* Transaction counter */}
      <div className="absolute top-4 left-4 bg-slate-900/90 backdrop-blur px-3 py-2 rounded-lg border border-slate-700 z-[1000]">
        <div className="text-xs text-slate-400">Live Transactions</div>
        <div className="text-lg font-mono text-white">{recentTxns.length}</div>
      </div>
    </div>
  );
};

export default WorldMap;
