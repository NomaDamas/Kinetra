import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '../index.css'
import './present.css'
import { Presenter } from './Presenter'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Presenter />
  </StrictMode>,
)
