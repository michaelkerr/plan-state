CREATE TABLE IF NOT EXISTS domains (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  location        TEXT,
  notes           TEXT,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activities (
  id              TEXT PRIMARY KEY,
  domain_id       TEXT NOT NULL REFERENCES domains(id),
  name            TEXT NOT NULL,
  description     TEXT,
  group_name      TEXT,
  status          TEXT DEFAULT 'watching'
                    CHECK(status IN ('watching','preparing','active','completed','skipped')),
  trigger_type    TEXT CHECK(trigger_type IN ('calendar','condition','dependency','compound')),
  trigger_def     JSON,
  trigger_date    DATE,
  trigger_fired   DATETIME,
  completed_at    DATETIME,
  sort_order      INTEGER DEFAULT 0,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS steps (
  id              TEXT PRIMARY KEY,
  activity_id     TEXT NOT NULL REFERENCES activities(id),
  name            TEXT NOT NULL,
  description     TEXT,
  step_type       TEXT NOT NULL CHECK(step_type IN ('prep','follow_up')),
  lead_days       INTEGER NOT NULL DEFAULT 0,
  status          TEXT DEFAULT 'pending'
                    CHECK(status IN ('pending','due','completed','skipped')),
  due_date        DATE,
  completed_at    DATETIME,
  sort_order      INTEGER DEFAULT 0,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conditions (
  id              TEXT PRIMARY KEY,
  activity_id     TEXT NOT NULL REFERENCES activities(id),
  condition_type  TEXT NOT NULL CHECK(condition_type IN ('temperature','weather_event','calendar','dependency')),
  definition      JSON NOT NULL,
  current_value   REAL,
  is_met          BOOLEAN DEFAULT 0,
  last_checked    DATETIME
);

CREATE TABLE IF NOT EXISTS weather_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  location        TEXT NOT NULL,
  weather_date    TEXT NOT NULL,          -- local calendar day; one row per location per day
  recorded_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  temp_high       REAL,
  temp_low        REAL,
  conditions      TEXT,
  precipitation   REAL,
  forecast_json   JSON,
  UNIQUE(location, weather_date)
);

CREATE TABLE IF NOT EXISTS activity_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
  item_type       TEXT NOT NULL CHECK(item_type IN ('domain','activity','step','condition')),
  item_id         TEXT NOT NULL,
  action          TEXT NOT NULL CHECK(action IN ('status_change','date_cascade','trigger_fire','manual_update','created','observation')),
  old_value       JSON,
  new_value       JSON,
  source          TEXT NOT NULL CHECK(source IN ('cron','hermes','claude','human')),
  batch_id        TEXT
);

CREATE INDEX IF NOT EXISTS idx_activities_domain ON activities(domain_id);
CREATE INDEX IF NOT EXISTS idx_activities_status ON activities(status);
CREATE INDEX IF NOT EXISTS idx_steps_activity ON steps(activity_id);
CREATE INDEX IF NOT EXISTS idx_conditions_activity ON conditions(activity_id);
CREATE INDEX IF NOT EXISTS idx_weather_location ON weather_log(location, recorded_at);
CREATE INDEX IF NOT EXISTS idx_activity_log_item ON activity_log(item_type, item_id);
CREATE INDEX IF NOT EXISTS idx_activity_log_batch ON activity_log(batch_id);
