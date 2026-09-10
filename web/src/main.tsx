import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import ObservabilityPanel from './ObservabilityPanel';
import OptimizerPanel from './OptimizerPanel';
import ProfileManagerPanel from './ProfileManagerPanel';
import BenchmarkTrendsPanel from './BenchmarkTrendsPanel';
import RuntimeRecoveryBanner from './RuntimeRecoveryBanner';
import ModelInspectorPanel from './ModelInspectorPanel';
import ReleaseReadinessPanel from './ReleaseReadinessPanel';
import './styles.css';
import './trust.css';
import './utility-rail.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
    <RuntimeRecoveryBanner />
    <ModelInspectorPanel />
    <BenchmarkTrendsPanel />
    <ProfileManagerPanel />
    <OptimizerPanel />
    <ObservabilityPanel />
    <ReleaseReadinessPanel />
  </React.StrictMode>
);
