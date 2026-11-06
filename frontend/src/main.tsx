import '@fontsource-variable/atkinson-hyperlegible-mono';
import '@fontsource-variable/atkinson-hyperlegible-next';
import '@fontsource-variable/big-shoulders-display';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './styles.css';

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
