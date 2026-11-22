CREATE TABLE IF NOT EXISTS schema_versions(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS users(
    id bigserial PRIMARY KEY, username varchar(64) UNIQUE NOT NULL,
    password_hash text NOT NULL, role text NOT NULL CHECK(role IN ('visualizador','operador','administrador')),
    active boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS devices(id text PRIMARY KEY, name text NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log(
    id bigserial PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(),
    user_id bigint REFERENCES users(id), action text NOT NULL,
    device_id text REFERENCES devices(id), details jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS audit_created_idx ON audit_log(created_at DESC);
CREATE TABLE IF NOT EXISTS login_attempts(
    id bigserial PRIMARY KEY, username varchar(64) NOT NULL, ip text NOT NULL,
    success boolean NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS login_attempts_time_idx ON login_attempts(created_at);
CREATE TABLE IF NOT EXISTS login_sessions(
    id uuid PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id),
    expires_at timestamptz NOT NULL, revoked boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS ws_tickets(
    ticket_hash text PRIMARY KEY, login_id uuid NOT NULL REFERENCES login_sessions(id),
    expires_at timestamptz NOT NULL, used_at timestamptz
);
CREATE TABLE IF NOT EXISTS charging_sessions(
    id uuid PRIMARY KEY, device_id text NOT NULL REFERENCES devices(id),
    started_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL,
    ended_at timestamptz, status text NOT NULL CHECK(status IN ('charging','paused','completed','ended')),
    initial_battery_percent double precision NOT NULL, battery_percent double precision NOT NULL,
    capacity_kwh double precision NOT NULL, power_kw double precision NOT NULL,
    energy_kwh double precision NOT NULL, estimated_minutes double precision,
    estimated_completion timestamptz
);
CREATE INDEX IF NOT EXISTS sessions_device_time_idx ON charging_sessions(device_id,last_seen_at DESC);
CREATE TABLE IF NOT EXISTS command_outbox(
    id uuid PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id),
    device_id text NOT NULL REFERENCES devices(id), event jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
    published_at timestamptz, applied_at timestamptz
);
INSERT INTO schema_versions(version) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS jobs(
    id uuid PRIMARY KEY, kind text NOT NULL CHECK(kind IN ('generate','train')),
    user_id bigint NOT NULL REFERENCES users(id), config jsonb NOT NULL,
    status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','failed')),
    progress double precision NOT NULL DEFAULT 0, message text NOT NULL DEFAULT 'Na fila',
    result jsonb, published_at timestamptz, attempts integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz, finished_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS one_lab_job_at_a_time ON jobs((true)) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS model_versions(
    id uuid PRIMARY KEY, job_id uuid UNIQUE NOT NULL REFERENCES jobs(id),
    dataset_id uuid NOT NULL REFERENCES jobs(id), accepted boolean NOT NULL,
    active boolean NOT NULL DEFAULT false, metrics jsonb NOT NULL, artifact_path text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_model_version ON model_versions((true)) WHERE active;
INSERT INTO schema_versions(version) VALUES (2) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS predictive_alerts(
    id uuid PRIMARY KEY, device_id text NOT NULL REFERENCES devices(id),
    severity text NOT NULL CHECK(severity IN ('warning','critical')),
    active boolean NOT NULL DEFAULT true, opened_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL, closed_at timestamptz,
    model_id uuid REFERENCES model_versions(id), reason text NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_predictive_alert_per_device ON predictive_alerts(device_id) WHERE active;
CREATE TABLE IF NOT EXISTS processed_alert_events(id uuid PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now());
INSERT INTO schema_versions(version) VALUES (3) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS device_components(
    id text PRIMARY KEY, device_id text NOT NULL REFERENCES devices(id),
    name text NOT NULL, kind text NOT NULL CHECK(kind IN ('sensor','actuator','equipment')),
    telemetry_key text, normal_min double precision, normal_max double precision,
    critical_min double precision, critical_max double precision
);
INSERT INTO schema_versions(version) VALUES (4) ON CONFLICT DO NOTHING;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS location varchar(120) NOT NULL DEFAULT '';
ALTER TABLE devices ADD COLUMN IF NOT EXISTS description varchar(300) NOT NULL DEFAULT '';
ALTER TABLE devices ADD COLUMN IF NOT EXISTS commands_enabled boolean NOT NULL DEFAULT true;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 1;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE device_components ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 1;
ALTER TABLE device_components ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
INSERT INTO schema_versions(version) VALUES (5) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS assistant_requests(
    id uuid PRIMARY KEY, conversation_id uuid NOT NULL, user_id bigint NOT NULL REFERENCES users(id),
    question varchar(1200) NOT NULL, answer text NOT NULL DEFAULT '', model text NOT NULL,
    status text NOT NULL CHECK(status IN ('running','completed','cancelled','failed')),
    context_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
    error text, output_tokens integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS assistant_user_time_idx ON assistant_requests(user_id,created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS one_assistant_request_running ON assistant_requests((true)) WHERE status='running';
INSERT INTO schema_versions(version) VALUES (6) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS automation_rules(
    id text PRIMARY KEY, name text NOT NULL, description text NOT NULL,
    parameters jsonb NOT NULL, execution_location text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO schema_versions(version) VALUES (7) ON CONFLICT DO NOTHING;
