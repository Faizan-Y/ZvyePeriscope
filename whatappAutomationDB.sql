-- ============================================================
-- ZYVEFIT WHATSAPP AUTOMATION
-- Initial PostgreSQL Database Schema
-- ============================================================


-- ============================================================
-- 1. TIERS
-- ============================================================

CREATE TABLE tiers (
    tier_id SERIAL PRIMARY KEY,

    tier_name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================
-- 2. PHASES
-- ============================================================

CREATE TABLE phases (
    phase_id SERIAL PRIMARY KEY,

    phase_name VARCHAR(50) NOT NULL UNIQUE,
    phase_number INTEGER NOT NULL UNIQUE,

    start_day INTEGER NOT NULL,
    end_day INTEGER NOT NULL,

    description TEXT,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_phase_days
        CHECK (start_day >= 1 AND end_day >= start_day)
);


-- ============================================================
-- 3. MEMBERS
-- ============================================================

CREATE TABLE members (
    member_id SERIAL PRIMARY KEY,

    member_code VARCHAR(50) UNIQUE,
    member_name VARCHAR(150) NOT NULL,

    phone_number VARCHAR(30),
    whatsapp_sender_id VARCHAR(100),

    joining_date DATE NOT NULL,

    tier_id INTEGER REFERENCES tiers(tier_id),
    phase_id INTEGER REFERENCES phases(phase_id),

    -- FALSE = phase is automatically calculated
    -- TRUE  = nutritionist manually changed the phase
    phase_override BOOLEAN NOT NULL DEFAULT FALSE,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================
-- 4. WHATSAPP GROUPS
-- ============================================================

CREATE TABLE whatsapp_groups (
    group_id SERIAL PRIMARY KEY,

    periskope_chat_id VARCHAR(150) NOT NULL UNIQUE,
    group_name VARCHAR(255),

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================
-- 5. GROUP MEMBERS
-- ============================================================

CREATE TABLE group_members (
    group_id INTEGER NOT NULL
        REFERENCES whatsapp_groups(group_id)
        ON DELETE CASCADE,

    member_id INTEGER NOT NULL
        REFERENCES members(member_id)
        ON DELETE CASCADE,

    joined_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    left_at TIMESTAMP,

    PRIMARY KEY (group_id, member_id)
);


-- ============================================================
-- 6. MESSAGE TEMPLATES
-- ============================================================

CREATE TABLE templates (
    template_id SERIAL PRIMARY KEY,

    template_code VARCHAR(100) NOT NULL UNIQUE,
    template_name VARCHAR(150) NOT NULL,

    message_type VARCHAR(30) NOT NULL DEFAULT 'TEXT',

    message_content TEXT NOT NULL,

    media_url TEXT,

    language VARCHAR(20) NOT NULL DEFAULT 'en',

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_template_message_type
        CHECK (
            message_type IN (
                'TEXT',
                'IMAGE',
                'VIDEO',
                'AUDIO',
                'DOCUMENT',
                'LOCATION'
            )
        )
);


-- ============================================================
-- 7. MESSAGE SCHEDULES
-- ============================================================

CREATE TABLE message_schedules (
    schedule_id SERIAL PRIMARY KEY,

    tier_id INTEGER NOT NULL
        REFERENCES tiers(tier_id),

    phase_id INTEGER
        REFERENCES phases(phase_id),

    -- Day of member journey.
    -- Joining date = Day 1.
    day_offset INTEGER,

    task_type VARCHAR(100) NOT NULL,

    template_id INTEGER NOT NULL
        REFERENCES templates(template_id),

    -- Supported schedule types:
    -- ONCE
    -- DAILY
    -- WEEKLY
    -- FORTNIGHTLY
    -- HOURLY
    schedule_type VARCHAR(30) NOT NULL DEFAULT 'DAILY',

    send_time TIME,

    -- Used for HOURLY schedules.
    -- Example: 08:00 to 20:00 every 60 minutes.
    start_time TIME,
    end_time TIME,
    interval_minutes INTEGER,

    -- Used for WEEKLY schedules.
    -- PostgreSQL:
    -- 0 = Sunday
    -- 1 = Monday
    -- ...
    -- 6 = Saturday
    day_of_week INTEGER,

    -- Used when a schedule should happen on a particular
    -- calendar day, if required later.
    day_of_month INTEGER,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_schedule_type
        CHECK (
            schedule_type IN (
                'ONCE',
                'DAILY',
                'WEEKLY',
                'FORTNIGHTLY',
                'HOURLY'
            )
        ),

    CONSTRAINT chk_schedule_day_offset
        CHECK (
            day_offset IS NULL OR day_offset >= 1
        ),

    CONSTRAINT chk_schedule_interval
        CHECK (
            interval_minutes IS NULL OR interval_minutes > 0
        ),

    CONSTRAINT chk_day_of_week
        CHECK (
            day_of_week IS NULL
            OR day_of_week BETWEEN 0 AND 6
        ),

    CONSTRAINT chk_day_of_month
        CHECK (
            day_of_month IS NULL
            OR day_of_month BETWEEN 1 AND 31
        )
);


-- ============================================================
-- 8. MESSAGE LOGS
-- ============================================================

CREATE TABLE message_logs (
    message_log_id BIGSERIAL PRIMARY KEY,

    member_id INTEGER
        REFERENCES members(member_id),

    group_id INTEGER
        REFERENCES whatsapp_groups(group_id),

    schedule_id INTEGER
        REFERENCES message_schedules(schedule_id),

    template_id INTEGER
        REFERENCES templates(template_id),

    message_type VARCHAR(30) NOT NULL DEFAULT 'TEXT',

    message_content TEXT,

    media_url TEXT,

    periskope_message_id VARCHAR(150),

    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',

    error_message TEXT,

    scheduled_at TIMESTAMP,

    sent_at TIMESTAMP,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_message_log_status
        CHECK (
            status IN (
                'PENDING',
                'QUEUED',
                'SENT',
                'DELIVERED',
                'READ',
                'FAILED'
            )
        )
);


-- ============================================================
-- 9. INCOMING MESSAGES
-- ============================================================

CREATE TABLE incoming_messages (
    incoming_message_id BIGSERIAL PRIMARY KEY,

    group_id INTEGER
        REFERENCES whatsapp_groups(group_id),

    member_id INTEGER
        REFERENCES members(member_id),

    periskope_message_id VARCHAR(150),

    message_type VARCHAR(30) NOT NULL DEFAULT 'TEXT',

    message_content TEXT,

    media_url TEXT,

    received_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_incoming_message_type
        CHECK (
            message_type IN (
                'TEXT',
                'IMAGE',
                'VIDEO',
                'AUDIO',
                'DOCUMENT',
                'LOCATION'
            )
        )
);


-- ============================================================
-- INDEXES
-- ============================================================


-- MEMBERS

CREATE INDEX idx_members_member_code
    ON members(member_code);

CREATE INDEX idx_members_whatsapp_sender
    ON members(whatsapp_sender_id);

CREATE INDEX idx_members_tier
    ON members(tier_id);

CREATE INDEX idx_members_phase
    ON members(phase_id);

CREATE INDEX idx_members_joining_date
    ON members(joining_date);

CREATE INDEX idx_members_active
    ON members(is_active);


-- GROUP MEMBERS

CREATE INDEX idx_group_members_member
    ON group_members(member_id);

CREATE INDEX idx_group_members_group
    ON group_members(group_id);


-- MESSAGE SCHEDULES

CREATE INDEX idx_message_schedules_tier_phase
    ON message_schedules(tier_id, phase_id);

CREATE INDEX idx_message_schedules_active
    ON message_schedules(is_active);

CREATE INDEX idx_message_schedules_day_offset
    ON message_schedules(day_offset);


-- MESSAGE LOGS

CREATE INDEX idx_message_logs_member
    ON message_logs(member_id);

CREATE INDEX idx_message_logs_group
    ON message_logs(group_id);

CREATE INDEX idx_message_logs_schedule
    ON message_logs(schedule_id);

CREATE INDEX idx_message_logs_template
    ON message_logs(template_id);

CREATE INDEX idx_message_logs_status
    ON message_logs(status);

CREATE INDEX idx_message_logs_created_at
    ON message_logs(created_at);


-- INCOMING MESSAGES

CREATE INDEX idx_incoming_messages_member
    ON incoming_messages(member_id);

CREATE INDEX idx_incoming_messages_group
    ON incoming_messages(group_id);

CREATE INDEX idx_incoming_messages_received_at
    ON incoming_messages(received_at);