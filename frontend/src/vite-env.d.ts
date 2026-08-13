/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the GridSense API. Inlined at build time by Vite — changing
   *  it in the host dashboard requires a rebuild, not just a restart. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
