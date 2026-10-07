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
