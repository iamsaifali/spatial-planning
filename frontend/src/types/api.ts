/** Mirrors backend Pydantic contracts (app/models). All lengths in cm. */

export type Point = [number, number];

export type DoorSwing = "inward" | "outward" | "sliding" | "opening_only";
export type Hinge = "left" | "right";

export interface Door {
  id: string;
  wall_index: number;
  offset_cm: number;
  width_cm: number;
  height_cm: number; // drives the 3D lintel
  swing: DoorSwing;
  hinge: Hinge;
}

export interface Window {
  id: string;
  wall_index: number;
  offset_cm: number;
  width_cm: number;
  sill_height_cm: number;
  height_cm: number;
}

export interface Room {
  vertices: Point[];
  doors: Door[];
  windows: Window[];
  wall_height_cm: number;
}

export interface Pose {
  x: number;
  y: number;
  rotation_deg: number;
}

export interface CustomItemSpec {
  name: string;
  width_cm: number;
  depth_cm: number;
  height_cm: number;
}

export interface PlacedItem extends Pose {
  instance_id: string;
  product_id: string;
  zone_id?: string | null;
  custom?: CustomItemSpec | null;
}

export type Category =
  | "sofa"
  | "tv_unit"
  | "rug"
  | "coffee_table"
  | "side_table"
  | "accent_chair"
  | "lighting"
  | "storage"
  | "decor"
  | "custom";

export type StyleTag = "modern" | "scandinavian" | "industrial" | "boho" | "classic" | "minimal";

export interface Product {
  id: string;
  name: string;
  brand: string;
  category: Category;
  price: number;
  mrp?: number | null;
  width_cm: number;
  depth_cm: number;
  height_cm: number;
  style_tags: StyleTag[];
  colors: string[];
  materials: string[];
  in_stock: boolean;
  delivery_days: number;
  rating: number;
  attrs: Record<string, number>;
  image_url: string;
  is_walkable: boolean;
  shape: "rect" | "round";
  description: string;
}

export type RoomPurpose = "family" | "entertaining" | "compact_living" | "work_lounge";
// Top-level engine selector (separate from room_purpose, which flavours the living-room
// engine). "majlis" routes to the perimeter-seating Majlis engine.
export type RoomType = "living_room" | "majlis";

export interface Preferences {
  styles: StyleTag[];
  budget_tier: "budget" | "mid" | "premium" | null;
  total_budget: number | null;
  colors: string[];
  room_type: RoomType;
  room_purpose: RoomPurpose | null;
  seating_capacity: number | null;
}

export const EMPTY_PREFERENCES: Preferences = {
  styles: [],
  budget_tier: null,
  total_budget: null,
  colors: [],
  room_type: "living_room",
  room_purpose: null,
  seating_capacity: null,
};

// --- analysis ---

export interface OpeningSpan {
  kind: "door" | "window";
  id: string;
  start_cm: number;
  end_cm: number;
}

export interface WallInfo {
  index: number;
  start: Point;
  end: Point;
  length_cm: number;
  inward_normal: Point;
  openings: OpeningSpan[];
  clear_floor_segments: [number, number][];
  clear_solid_segments: [number, number][];
  is_longest_clear: boolean;
  is_focal: boolean;
}

export interface Entry {
  door_id: string;
  point: Point;
  is_primary: boolean;
}

export interface Corridor {
  id: string;
  from_label: string;
  to_label: string;
  polyline: Point[];
  polygon: Point[];
  width_cm: number;
}

export interface Zone {
  id: string;
  category: Category;
  polygon: Point[];
  score: number;
  suggested_rotation_deg: number;
  anchor: string;
  reason_codes: string[];
  rank: number;
}

export interface RoomMetrics {
  area_m2: number;
  perimeter_cm: number;
  bbox_w_cm: number;
  bbox_h_cm: number;
}

export interface AnalysisResponse {
  analysis_hash: string;
  metrics: RoomMetrics;
  walls: WallInfo[];
  entries: Entry[];
  keep_clear: Point[][];
  window_strips: Point[][];
  corridors: Corridor[];
  usable_area: Point[][];
  focal_wall_index: number | null;
  zones: Zone[];
  notices: string[];
}

export interface RoomIssue {
  code: string;
  message: string;
  wall_index: number | null;
}

export interface RoomValidateResponse {
  valid: boolean;
  issues: RoomIssue[];
}

// --- placement ---

export type Severity = "error" | "warning" | "info";

export interface Finding {
  code: string;
  severity: Severity;
  message: string;
  item_instance_id: string | null;
  other_instance_id: string | null;
  geometry: Point[] | null;
}

export interface AutoFix {
  pose: Pose;
  resolves: string[];
}

export interface BetterPlacement {
  pose: Pose;
  zone_id: string | null;
}

export interface ValidateResponse {
  findings: Finding[];
  autofix: AutoFix | null;
  better_placement: BetterPlacement | null;
}

export interface SuggestResponse {
  pose: Pose;
  zone_id: string | null;
  alternatives: Pose[];
}

// --- guide ---

export type CopySource = "llm" | "template" | "offline";

export interface WhyItFits {
  why_product: string;
  why_size: string;
  why_placement: string;
  copy_source: CopySource;
}

export interface Recommendation {
  rank: number; // 0 = best style+colour match
  product: Product;
  why_it_fits: WhyItFits;
  suggested_pose: Pose;
  zone_id: string | null;
  fit_facts: Record<string, number | string | boolean>;
  notices: string[];
}

export interface NoFit {
  reason: string;
  hints: Record<string, number | string>;
}

export interface Guidance {
  message: string;
  tip: string | null;
  reason_codes: string[];
  copy_source: CopySource;
}

export interface StepInfo {
  key: string;
  category: Category;
  title: string;
  order: number;
  status: "done" | "current" | "pending";
  quantity: number;
  placed_count: number;
}

export interface StepsResponse {
  steps: StepInfo[];
}

export interface StepResponse {
  analysis_hash: string;
  step_key: string;
  guidance: Guidance;
  zones: Zone[];
  recommendations: Recommendation[];
  no_fit: NoFit | null;
  quantity: number;
}

// --- layout plan ---

export interface PlanItem {
  category: Category;
  quantity: number;
  tier: "essential" | "non_essential";
  priority: number;
}

export interface LayoutPlan {
  archetype: string;
  items: PlanItem[];
  rationale: string;
  /** Set when requested seating exceeds what the room holds; explains the shortfall. */
  seating_note?: string | null;
}

export interface PlanResponse {
  plan: LayoutPlan;
  steps: StepInfo[];
  plan_source: CopySource;
}

// --- summary / commerce ---

export interface SummaryLine {
  product: Product;
  pose: PlacedItem;
  instance_id: string;
  line_price: number;
}

export interface MissingEssential {
  category: Category;
  label: string;
  reason: string;
}

export interface SuggestedUpgrade {
  from_product_id: string;
  from_name: string;
  to_product: Product;
  delta: number;
  reason: string;
}

export interface SummaryResponse {
  items: SummaryLine[];
  total_price: number;
  by_category: Record<string, number>;
  completeness_pct: number;
  missing_essentials: MissingEssential[];
  suggested_upgrades: SuggestedUpgrade[];
  layout_findings: Finding[];
  narrative: { text: string; copy_source: CopySource };
}

export interface RenderResponse {
  image_b64: string;
  prompt_facts: Record<string, unknown>;
}

export interface AssistantResponse {
  answer: string;
  related_tip: string | null;
  facts_used: string[];
  copy_source: CopySource;
}

export interface DesignCreateResponse {
  design_id: string;
  share_path: string;
}

export interface DesignResponse {
  design_id: string;
  name: string;
  room: Room;
  placed_items: PlacedItem[];
  preferences: Preferences;
  total_price: number;
  item_count: number;
  created_at: string;
  updated_at: string;
}

export interface OrderLine {
  product_id: string;
  name: string;
  qty: number;
  unit_price: number;
}

export interface OrderResponse {
  order_id: string;
  status: string;
  total: number; // base currency
  currency: string;
  display_total: number; // converted at order time
  eta_days: number;
  lines: OrderLine[];
  created_at: string;
}

export interface CurrencyConfig {
  supported: string[];
  base: string;
  default: string;
  rates: Record<string, number>;
}

export interface SceneConfig {
  wall_thickness_cm: number;
}

export interface AppConfigResponse {
  currency: CurrencyConfig;
  scene: SceneConfig;
}

export interface ProductListResponse {
  items: Product[];
  total: number;
  page: number;
  page_size: number;
}

export interface HealthResponse {
  status: string;
  version: string;
  llm_enabled: boolean;
  render_enabled: boolean;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown };
}
