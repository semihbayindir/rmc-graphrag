export interface RecentQuestion {
  ts: number;
  question?: string | null;
  primary_module?: string | null;
  evidence_count: number;
  answered: number;
  latency_ms?: number | null;
  total_tokens?: number | null;
  synth_model?: string | null;
}

export interface UsageOverview {
  total_questions: number;
  questions_last_7d: number;
  answered: number;
  answered_rate: number | null;
  zero_evidence_count: number;
  zero_evidence_rate: number | null;
  distinct_sessions: number;
  avg_latency_ms: number | null;
  total_prompt_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  top_modules: { module: string; c: number }[];
  recent: RecentQuestion[];
  feedback: { up: number; down: number };
}

export interface HistoryTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ActiveContext {
  module?: string | null;
  channel?: string | null;
}

export interface RouterStep {
  intent: number;
  module?: string | null;
  channel?: string | null;
  activity?: string | null;
  keywords: string[];
  count: number;
}

export interface EvidenceRow {
  ticket_id: string | number;
  incident_id: string | number;
  skor?: number | null;
  symptom?: string | null;
  findings?: string | null;
  root_cause?: string | null;
  resolution?: string | null;
  outcome?: string | null;
  modul?: string | null;
  feature?: string | null;
  kanallar: string[];
  faaliyetler: string[];
  ekipler: string[];
  tarih?: string | null;
  artifacts: { ad: string; tip: string }[];
  rrf?: number | null;
}

export interface DocRow {
  id: string;
  protocol: string;
  service: string;
  method?: string | null;
  summary: string;
  url: string;
  text: string;
  reason: string;
}

export interface ChatResponse {
  question: string;
  standalone_question: string;
  router: RouterStep[];
  evidence: EvidenceRow[];
  docs?: DocRow[];
  answer: string;
  synth_model?: string | null;
  smalltalk?: boolean; // selamlama/teşekkür — arama yapılmadı, sabit cevap
  active_context: ActiveContext;
}

export interface ModelsResponse {
  synth_models: string[];
  default_synth_model: string;
}
