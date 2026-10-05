import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles/tokens.css';
import './styles/global.css';
import './styles/shell.css';
import './styles/chat.css';
import './styles/answers.css';
import './styles/auth.css';
import './styles/conversations.css';
import './styles/polish.css';
import './styles/motion.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode><App /></StrictMode>,
);
