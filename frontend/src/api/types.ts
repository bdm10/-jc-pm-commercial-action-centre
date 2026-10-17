// Response shapes of the FastAPI backend (see backend/app/api).

export type Entity = "JC" | "PM";
export type OppType = "transfer_no_reorder" | "declining_purchases" | "overdue_cadence";
export type Band = "high" | "medium" | "low";
export type ActionType = "contacted" | "meeting_booked" | "offer_requested" | "no_response" | "not_relevant";

export interface Meta {
  app_env: string;
  auth_mode: "demo" | "entra" | null;
  auth_configured: boolean;
  demo_mode: boolean;
  ai_enabled: boolean;
}

export interface Freshness {
  entity: Entity;
  source_model: string;
  refreshed_at: string;
  as_of: string;
  last_complete_month: string;
  data_classification: "synthetic" | "anonymised" | "live";
  is_stale: boolean;
  stale_after_hours: number;
}

export interface Me {
  id: number;
  email: string;
  display_name: string;
  role: "sales" | "manager" | "admin";
  teams_managed: string[];
  teams_member: string[];
  options: {
    action_types: ActionType[];
    dismiss_reasons: string[];
    snooze_options_days: number[];
    follow_up_max_days_ahead: number;
    today_max_cards: number;
  };
  config_version: number;
  rules_status: string;
  freshness: Freshness[];
  today: string;
}

export interface Provenance {
  type: string;
  measure_code?: string;
  measure_name?: string;
  certification_status?: string;
  source_model?: string;
  refreshed_at?: string;
  period?: { start: string; end: string };
  derivation?: string;
  formula_key?: string;
  inputs?: string[];
  mapping_ref?: string;
  approved_by?: string | null;
}

export interface EvidenceItem {
  id: string;
  label_key: string;
  kind: "money" | "date" | "days" | "count" | "pct" | "text";
  value: number | string;
  unit?: string;
  entity: Entity | null;
  provenance: Provenance;
  data_as_of?: string;
}

export interface CustomerBrief {
  source_entity: Entity;
  source_customer_id: string;
  display_name: string | null;
  city: string | null;
  channel: string | null;
  in_current_extract: boolean;
}

export interface ObservedOutcome {
  outcome_code: string;
  label: string;
  first_action_at: string;
  observed_document_date: string;
  observed_document_ref: string;
}

export interface Opportunity {
  id: number;
  opp_type: OppType;
  status: "open" | "in_progress" | "snoozed" | "dismissed" | "resolved";
  condition_active: boolean;
  priority_band: Band;
  priority_score: number;
  reason_code: string;
  reason_params: Record<string, string | number>;
  next_action: string | null;
  key_figures: EvidenceItem[];
  data_refreshed_at: string;
  first_detected_at: string;
  last_action_at: string | null;
  snoozed_until: string | null;
  dismissed_reason: string | null;
  resolved_at: string | null;
  resolution_code: string | null;
  observed_outcome: ObservedOutcome | null;
  evidence?: EvidenceItem[];
  priority_components?: {
    type_weight: number;
    value_factor: number;
    urgency: number;
    size_value: number;
    size_evidence_id: string | null;
    thresholds: { high: number; medium: number };
  };
  snooze_reason?: string | null;
  dismissed_note?: string | null;
}

export interface LastAction {
  action_type: ActionType;
  note: string | null;
  created_at: string;
}

export interface FollowUp {
  id: number;
  due_date: string;
  status: string;
  days_overdue: number;
  owner: { id: number; display_name: string };
  customer: CustomerBrief;
  opportunity_id: number | null;
  opp_type: OppType | null;
  last_action: LastAction | null;
  closed_at: string | null;
}

export interface TodayCard {
  customer: CustomerBrief;
  assignee: { id: number | null; display_name: string | null };
  opportunity: Opportunity;
  other_signals: { id: number; opp_type: OppType }[];
}

export interface Today {
  date: string;
  freshness: Freshness[];
  follow_ups_due: FollowUp[];
  cards: TodayCard[];
  more_count: number;
  hidden_due_to_stale_data: number;
  config_version: number;
}

export interface CustomerListItem extends CustomerBrief {
  assignee: { id: number | null; display_name: string | null };
  opportunities: { id: number; opp_type: OppType; status: string; priority_band: Band }[];
  best_priority: Band | null;
  last_order_date: string | null;
  has_data_issue: boolean;
}

export interface TalkingPoint {
  key?: string;
  text?: string;
  params?: Record<string, string | number>;
  fact_ids: string[];
}

export interface MeasureInfo {
  code: string;
  name_es: string;
  name_en: string;
  certified_measure_name: string;
  certification_status: string;
  source_model: string;
  unit: string;
}

export interface CustomerDetail {
  customer: CustomerBrief & {
    segment: string | null;
    province: string | null;
    is_intercompany: boolean;
    seasonal_flag: boolean | null;
    transfer_cohort: string | null;
    source_status: string | null;
  };
  assignee: { id: number | null; display_name: string | null };
  freshness: Freshness[];
  summary: {
    entity: Entity;
    last_order_date: string | null;
    measure?: MeasureInfo;
    last_12m?: { value: number; start: string; end: string };
    prior_12m?: { value: number; start: string; end: string };
    monthly?: { month: string; value: number }[];
    orders_last_12m: number;
    typical_interval_days?: number;
  };
  linked_accounts: {
    direction: "inbound" | "outbound";
    mapping_ref: string;
    transfer_date: string;
    cohort: string | null;
    approved_by: string | null;
    other: { source_entity: Entity; source_customer_id: string; display_name: string | null; last_order_date: string | null; can_open: boolean };
  }[];
  data_issues: { severity: string; issue_code: string; detail: Record<string, unknown>; stage: string }[];
  rule_evaluations: { opp_type: OppType; status: string; detail_code: string; detail_params: Record<string, string | number> }[];
  opportunities: Opportunity[];
  closed_opportunities: Opportunity[];
  recent_documents: {
    document_ref: string;
    document_date: string;
    document_type: "invoice" | "credit_note";
    lines: { brand: string | null; sku: string | null; sku_description: string | null; quantity: number | null; unit: string | null; amount: number | null; amount_measure_code: string | null }[];
  }[];
  activities: {
    id: number;
    action_type: ActionType;
    note: string | null;
    created_at: string;
    user: { id: number; display_name: string };
    follow_up_date: string | null;
    opportunity_id: number | null;
    opp_type: OppType | null;
  }[];
  open_follow_ups: { id: number; due_date: string; owner: { id: number; display_name: string }; opportunity_id: number | null }[];
  talking_points: TalkingPoint[];
  config_version: number;
  lost_label_enabled: boolean;
}

export interface AiPoints {
  status: "ok" | "rejected" | "not_configured" | "no_evidence";
  detail?: string;
  points: TalkingPoint[];
  facts: { id: string; label: string; value: unknown; unit?: string; entity?: string }[];
  provider?: string;
  model?: string;
}

export interface FollowUpList {
  date: string;
  overdue: FollowUp[];
  today: FollowUp[];
  upcoming: FollowUp[];
  done_recent: FollowUp[];
}

export interface TeamView {
  teams: string[];
  members: {
    id: number;
    display_name: string;
    role: string;
    assigned_customers: number;
    active_opportunities: number;
    actions_last_30d: number;
    follow_ups_open: number;
    follow_ups_overdue: number;
    observed_outcomes_90d: number;
  }[];
  overdue_follow_ups: FollowUp[];
  opportunity_status: Record<OppType, Record<string, number>>;
  actions_last_30d: Record<string, number>;
  observed_outcomes: {
    opportunity_id: number;
    opp_type: OppType | null;
    customer: CustomerBrief;
    action: { action_type: ActionType; user: string } | null;
    first_action_at: string;
    observed_document_date: string;
  }[];
  data_issues: Record<string, number>;
  user_reported_data_problems: number;
}

export interface AssignmentList {
  items: (CustomerBrief & { assignee: { id: number | null; display_name: string | null }; active_opportunities: number })[];
  total: number;
  assignable_users: { id: number; display_name: string; role: string }[];
}
