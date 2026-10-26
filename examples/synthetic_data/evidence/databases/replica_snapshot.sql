-- Synthetic SQLite Snapshot of Read Replica
CREATE TABLE IF NOT EXISTS customer_profiles (
    resource_id TEXT PRIMARY KEY,
    user_id TEXT,
    email TEXT,
    account_status TEXT
);

CREATE TABLE IF NOT EXISTS customer_data_read_replica (
    resource_id TEXT PRIMARY KEY,
    user_id TEXT,
    email TEXT,
    origin_system TEXT,
    account_status TEXT
);

-- Case 002: surviving lingering record in read replica
INSERT INTO customer_data_read_replica (resource_id, user_id, email, origin_system, account_status)
VALUES ('account_002', 'synth_user_02', 'bob.old@sample.com', 'account_service', 'ACTIVE');
