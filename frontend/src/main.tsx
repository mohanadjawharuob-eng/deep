import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { SessionProvider, ThemeProvider } from "./lib/hooks";

import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/app.css";

const root = document.getElementById("root");
if (!root) throw new Error("No #root element — index.html is not what it should be");

createRoot(root).render(
  <StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <SessionProvider>
          <App />
        </SessionProvider>
      </BrowserRouter>
    </ThemeProvider>
  </StrictMode>,
);
