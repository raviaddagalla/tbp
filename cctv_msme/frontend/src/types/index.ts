export interface User {
  id: number;
  username: string;
  full_name: string;
  email: string;
  role: "worker" | "supervisor" | "admin";
  zone: string | null;
  is_active: boolean;
  created_at: string;
}

export interface Camera {
  id: number;
  name: string;
  rtsp_url: string;
  zone: string;
  location_label: string;
  is_active: boolean;
  sample_interval_seconds: number;
  retention_hours: number;
  clip_segment_seconds: number;
  anomaly_enabled: boolean;
  detector_enabled: boolean;
  reid_enabled: boolean;
  batch_reprocess_enabled: boolean;
  status: "online" | "offline" | "reconnecting";
  last_seen_at: string | null;
  connected_at: string | null;
  last_error: string;
  frames_processed: number;
  frames_indexed: number;
  alerts_count: number;
  created_at: string;
}

export interface Document {
  id: number;
  filename: string;
  doc_type: string;
  status: "pending" | "processing" | "processed" | "failed";
  error: string;
  pages: number;
  chunk_count: number;
  ocr_used: boolean;
  uploaded_by: number;
  created_at: string;
}

export interface VideoSearchHit {
  id: string;
  camera_id: number;
  camera_name: string;
  zone: string;
  timestamp: string;
  score: number;
  thumbnail_url: string;
  clip_url: string;
  clip_offset_seconds: number;
  explanation: string;
}

export interface EntitySearchHit {
  id: string;
  camera_id: number;
  camera_name: string;
  zone: string;
  timestamp: string;
  score: number;
  object_class: string;
  bbox: string;
  detection_confidence: number;
  tracklet_local_id: number;
  thumbnail_url: string;
  frame_thumbnail_url: string;
  clip_url: string;
  clip_offset_seconds: number;
  attrs: { color: string; clothing: string; ppe: string };
}

export interface EntitySearchResponse {
  query: string;
  object_class: string | null;
  hits: EntitySearchHit[];
  total: number;
  search_id: number;
}

export interface VideoSearchResponse {
  query: string;
  hits: VideoSearchHit[];
  total: number;
  search_id: number;
}

export interface TemporalSearchHit extends VideoSearchHit {
  window_start: string | null;
  window_end: string | null;
  frame_count: number;
}

export interface TemporalSearchResponse {
  query: string;
  hits: TemporalSearchHit[];
  total: number;
  temporal_used: boolean;
  search_id: number;
}

export interface DocumentSearchHit {
  id: string;
  document_id: number;
  filename: string;
  page: number;
  section: string;
  chunk_text: string;
  score: number;
}

export interface Citation {
  document_id: number;
  filename: string;
  page: number;
  section: string;
  score: number;
}

export interface VideoEvidence {
  camera_name: string;
  zone: string;
  timestamp: string;
  score: number;
  thumbnail_url: string;
  clip_url: string;
  clip_offset_seconds: number;
  description: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  video_evidence?: VideoEvidence[];
  intent?: { video: boolean; doc: boolean };
}

export interface ChatResponse {
  answer: string;
  language: string;
  citations: Citation[];
  video_evidence: VideoEvidence[];
  intent: { video: boolean; doc: boolean };
  provider: string;
}

export interface Summary {
  id: number;
  title: string;
  kind: string;
  content: string;
  created_by: string;
  window_start: string;
  window_end: string;
  tags_json: { tags?: string[] };
  created_at: string;
}

export interface Alert {
  id: number;
  camera_id: number;
  camera_name: string;
  zone: string;
  alert_type: string;
  description: string;
  score: number;
  timestamp: string;
  thumbnail_url: string;
  clip_url: string | null;
  clip_offset_seconds: number;
  status: "open" | "acknowledged" | "dismissed";
  trail: TrailStep[];
  report: string;
  acknowledged_by: string;
  acknowledged_at: string | null;
}

export interface AlertTimeline {
  alert_id: number;
  camera_id: number;
  clips: { segment_id: string; start: number; clip_url: string }[];
}

export interface TrailStep {
  camera_id: number;
  camera_name: string;
  zone: string;
  timestamp: string;
  score: number;
  thumbnail: string;
}

export interface AnalyticsOverview {
  cameras_total: number;
  cameras_online: number;
  frames_indexed: number;
  documents_total: number;
  documents_processed: number;
  chunks_indexed: number;
  searches_total: number;
  searches_last_7d: number;
  alerts_open: number;
  top_zones: { zone: string; count: number }[];
  searches_by_day: { date: string; count: number }[];
  document_usage: { filename: string; chunks: number; status: string; pages: number }[];
  activity: { kind: string; message: string; created_at: string }[];
}

export interface ActivityItem {
  id: number;
  kind: string;
  message: string;
  camera_id: number | null;
  created_at: string;
}

export interface LoadStatus {
  active_cameras: number;
  effective_sample_interval: number;
  llm_provider: string;
  llm_model: string;
  embedding_device: string;
  vector_store_backend: string;
  queue_depth: number;
}

export interface CameraDiagnostics {
  id: number;
  name: string;
  zone: string;
  status: string;
  last_seen_at: string | null;
  connected_at: string | null;
  last_error: string;
  frames_processed: number;
  frames_indexed: number;
  alerts_count: number;
  inflight: number;
  sample_interval_seconds: number;
  retention_hours: number;
  detector_enabled: boolean;
  reid_enabled: boolean;
  batch_reprocess_enabled: boolean;
  anomaly_enabled: boolean;
  object_vectors: number;
  clip_event_vectors: number;
}

export interface SystemDiagnostics {
  vector_store_backend: string;
  queue_depth: number;
  effective_sample_interval: number;
  llm_provider: string;
  llm_model: string;
  embedding_device: string;
  reid_model: string;
  data_dir: string;
  retention_hours: number;
  cameras: CameraDiagnostics[];
}

export interface AdjacencyEdge {
  id?: number;
  from_camera_id: number;
  from_camera_name: string;
  to_camera_id: number;
  to_camera_name: string;
  expected_transit_seconds_min: number;
  expected_transit_seconds_max: number;
  direction_label: string;
  floorplan_id?: string;
}

export interface FloorPlanState {
  adjacency: AdjacencyEdge[];
  image_url: string | null;
  pins: Record<string, { x: number; y: number }>;
}

export interface WsEvent {
  type: string;
  payload: Record<string, unknown>;
}
