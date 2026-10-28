import React from 'react';
import ReactDOM from 'react-dom/client';
import Stm32Window from './pages/Stm32Window';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><Stm32Window /></React.StrictMode>,
);
