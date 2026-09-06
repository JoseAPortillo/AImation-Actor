/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly AIMATION_SESSION_TOKEN?: string;
  readonly VITE_AIMATION_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
