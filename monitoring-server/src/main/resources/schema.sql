CREATE SEQUENCE IF NOT EXISTS event_seq START WITH 1 MAXVALUE 4294967295 NO CYCLE;
CREATE TABLE IF NOT EXISTS deliveries (
  message_id VARCHAR(36) PRIMARY KEY,
  camera_id VARCHAR(80) NOT NULL,
  event_id VARCHAR(36) NOT NULL,
  event_type VARCHAR(10) NOT NULL,
  age_group VARCHAR(10),
  seq BIGINT NOT NULL,
  gateway_id VARCHAR(80) NOT NULL,
  railing_id INT NOT NULL,
  observed_at VARCHAR(40) NOT NULL,
  expires_at VARCHAR(40) NOT NULL,
  status VARCHAR(20) NOT NULL,
  UNIQUE(camera_id, event_id, event_type)
);

CREATE TABLE IF NOT EXISTS portal_users (
  id VARCHAR(36) PRIMARY KEY, username VARCHAR(100) UNIQUE NOT NULL,
  name VARCHAR(100) NOT NULL, password_hash VARCHAR(100) NOT NULL,
  admin BOOLEAN NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS sites (
  id VARCHAR(80) PRIMARY KEY, name VARCHAR(100) NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
  user_id VARCHAR(36) NOT NULL REFERENCES portal_users(id),
  site_id VARCHAR(80) NOT NULL REFERENCES sites(id), role VARCHAR(10) NOT NULL,
  PRIMARY KEY(user_id,site_id)
);
CREATE TABLE IF NOT EXISTS portal_gateways (
  id VARCHAR(80) PRIMARY KEY, site_id VARCHAR(80) NOT NULL REFERENCES sites(id),
  name VARCHAR(100) NOT NULL, token_hash VARCHAR(100) NOT NULL
);
CREATE TABLE IF NOT EXISTS rails (
  id VARCHAR(36) PRIMARY KEY, gateway_id VARCHAR(80) NOT NULL REFERENCES portal_gateways(id),
  number INT NOT NULL, name VARCHAR(100) NOT NULL, latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION, address VARCHAR(200) NOT NULL DEFAULT '',
  snapshot VARCHAR(16000), seen_at BIGINT, UNIQUE(gateway_id,number)
);
CREATE TABLE IF NOT EXISTS cameras (
  id VARCHAR(80) PRIMARY KEY, rail_id VARCHAR(36) UNIQUE NOT NULL REFERENCES rails(id),
  stream_path VARCHAR(200) NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS commands (
  id VARCHAR(36) PRIMARY KEY, batch_id VARCHAR(36) NOT NULL,
  user_id VARCHAR(36) NOT NULL REFERENCES portal_users(id),
  gateway_id VARCHAR(80) NOT NULL REFERENCES portal_gateways(id),
  rail_id VARCHAR(36) NOT NULL REFERENCES rails(id), operation VARCHAR(40) NOT NULL,
  args VARCHAR(1000), created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL,
  status VARCHAR(20) NOT NULL, detail VARCHAR(200) NOT NULL DEFAULT '',
  UNIQUE(user_id,batch_id,rail_id)
);
CREATE TABLE IF NOT EXISTS calls (
  gateway_id VARCHAR(80) PRIMARY KEY REFERENCES portal_gateways(id),
  id VARCHAR(36) NOT NULL, rail_id VARCHAR(36) NOT NULL REFERENCES rails(id),
  user_id VARCHAR(36) NOT NULL REFERENCES portal_users(id),
  status VARCHAR(20) NOT NULL, direction VARCHAR(20) NOT NULL DEFAULT 'FIELD_TX',
  touched_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS telemetry_samples (
  id VARCHAR(36) PRIMARY KEY, rail_id VARCHAR(36) NOT NULL REFERENCES rails(id),
  observed_at BIGINT NOT NULL, left_watt DOUBLE PRECISION, right_watt DOUBLE PRECISION,
  battery_percent DOUBLE PRECISION, emergency BOOLEAN,
  UNIQUE(rail_id,observed_at)
);
CREATE TABLE IF NOT EXISTS schedules (
  rail_id VARCHAR(36) PRIMARY KEY REFERENCES rails(id), user_id VARCHAR(36) NOT NULL REFERENCES portal_users(id),
  start_time VARCHAR(5) NOT NULL, end_time VARCHAR(5) NOT NULL, enabled BOOLEAN NOT NULL,
  last_boundary VARCHAR(40) NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS contacts (
  site_id VARCHAR(80) NOT NULL REFERENCES sites(id), label VARCHAR(30) NOT NULL,
  phone VARCHAR(20) NOT NULL, PRIMARY KEY(site_id,label)
);
CREATE TABLE IF NOT EXISTS audit_log (
  id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, site_id VARCHAR(80) NOT NULL,
  action VARCHAR(100) NOT NULL, detail VARCHAR(500) NOT NULL, created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS commands_queue ON commands(gateway_id,status,created_at);
CREATE INDEX IF NOT EXISTS telemetry_period ON telemetry_samples(rail_id,observed_at);
CREATE INDEX IF NOT EXISTS audit_site ON audit_log(site_id,created_at);

CREATE TABLE IF NOT EXISTS sms_requests(id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36), site_id VARCHAR(80), label VARCHAR(30), rail_id VARCHAR(36), status VARCHAR(20), created_at BIGINT);
