export type CameraStatus = "online" | "offline" | "connecting" | "reconnecting" | "error";

export interface CameraStats {
  running: boolean;
  status: CameraStatus | string;
  last_error: string;
  source_url: string;
  source_kind: "mjpeg" | "snapshot" | "rtsp" | "simulated" | "none" | string;
  source_label: string;
  configured_fps: number;
  measured_fps: number;
  index_interval_seconds: number;
  detector_enabled: boolean;
  frame_width: number;
  frame_height: number;
  frames_received: number;
  frames_indexed: number;
  objects_detected: number;
  last_frame_at: string;
  index_pending: boolean;
}

export interface CameraConfig {
  stream_url: string;
  live_fps: number;
  index_interval_seconds: number;
  detector_enabled: boolean;
  auto_start: boolean;
  default_sample_fps: number;
  status: string;
  last_error: string;
  last_frame_at: string | null;
  frames_received: number;
  frames_indexed: number;
  objects_detected: number;
}

export interface DetectorStatus {
  model: string;
  ready: boolean;
  confidence_threshold: number;
  enabled: boolean;
}

export interface EmbedderStatus {
  model: string;
  device: string;
  loaded: boolean;
  dimension: number;
}

export interface AiStatus {
  detector: DetectorStatus;
  embedder: EmbedderStatus;
  vector_store: { backend: string; scenes: number; objects: number };
}

export interface StorageBucket {
  bytes: number;
  human: string;
  count?: number;
}

export interface StorageStatus {
  data_dir: string;
  database: StorageBucket;
  thumbnails: StorageBucket;
  snapshots: StorageBucket;
  recordings: StorageBucket;
  vectorstore: StorageBucket;
  max_upload_mb: number;
  index_frame_cap: number;
}

export interface ObjectClassCount {
  object_class: string;
  count: number;
}

export interface Totals {
  frames_total: number;
  live_frames: number;
  upload_frames: number;
  detections_total: number;
  recordings_total: number;
  recordings_ready: number;
  recordings_indexing: number;
  indexed_video_seconds: number;
  object_classes: ObjectClassCount[];
}

export interface DetectionItem {
  id: number;
  object_class: string;
  confidence: number;
  track_id: number;
  colour: string;
  bbox: [number, number, number, number];
  thumbnail_url: string;
  frame_thumbnail_url: string;
  captured_at: string;
  timestamp_seconds: number;
  source_type: "live" | "upload";
  recording_id: number | null;
  recording_name: string;
  frame_id: number;
  playback_url: string;
}

export interface ActivityItem {
  id: number;
  kind: string;
  message: string;
  recording_id: number | null;
  created_at: string;
}

export interface OverviewResponse {
  totals: Totals;
  camera: CameraStats;
  camera_config: CameraConfig;
  ai: AiStatus;
  storage: StorageStatus;
  recent_detections: DetectionItem[];
  activity: ActivityItem[];
}

export interface Recording {
  id: number;
  name: string;
  original_name: string;
  status: "queued" | "processing" | "ready" | "failed" | "cancelled";
  error: string;
  duration_seconds: number;
  fps: number;
  width: number;
  height: number;
  total_frames: number;
  sample_fps: number;
  frames_indexed: number;
  frames_planned: number;
  objects_detected: number;
  progress: number;
  thumbnail_url: string;
  playback_url: string;
  created_at: string;
  completed_at: string;
}

export interface LiveDetection {
  track_id: number;
  object_class: string;
  confidence: number;
  bbox: [number, number, number, number];
}

export interface LiveDetectionsResponse {
  detections: LiveDetection[];
  captured_at: string;
  status: string;
  source_kind: string;
  source_label: string;
  frame_width: number;
  frame_height: number;
  measured_fps: number;
}

export interface SearchHit {
  id: string;
  match_type: "scene" | "object";
  score: number;
  source_type: "live" | "upload";
  recording_id: number | null;
  recording_name: string;
  source_label: string;
  frame_id: number;
  frame_number: number;
  timestamp_seconds: number;
  captured_at: string;
  thumbnail_url: string;
  frame_thumbnail_url: string;
  object_class: string;
  track_id: number;
  confidence: number;
  bbox: number[];
  playback_url: string;
  detections: {
    object_class: string;
    track_id: number;
    confidence: number;
    bbox: [number, number, number, number];
    thumbnail: string;
    colour: string;
    timestamp_seconds: number;
  }[];
}

export interface SearchResponse {
  query: string;
  mode: "both" | "scene" | "object";
  total: number;
  min_score: number;
  hits: SearchHit[];
}

export interface FrameDetail {
  frame_id: number;
  recording_id: number | null;
  source_type: "live" | "upload";
  frame_number: number;
  timestamp_seconds: number;
  captured_at: string;
  thumbnail: string;
  thumbnail_url: string;
  width: number;
  height: number;
  objects_count: number;
  scene_vector_id: string;
  detections: {
    object_class: string;
    track_id: number;
    confidence: number;
    bbox: [number, number, number, number];
    thumbnail: string;
    colour: string;
    timestamp_seconds: number;
  }[];
}

export interface ProbeResult {
  ok: boolean;
  endpoint: string;
  kind: string;
  detail: string;
  width: number;
  height: number;
  preview_data_url: string;
}

export interface SettingsResponse {
  camera: CameraConfig;
  camera_runtime: CameraStats;
  indexing: {
    default_sample_fps: number;
    max_frames: number;
    max_upload_mb: number;
    thumbnail_max_width: number;
  };
  ai: AiStatus;
  storage: StorageStatus;
  server: {
    app_name: string;
    data_dir: string;
    vector_store_dir: string;
    indexer: { active: number | null; queued: number[] };
  };
}
