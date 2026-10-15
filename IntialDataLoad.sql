-- ============================================================
-- INITIAL MESSAGE TEMPLATES
-- Document templates are seeded for configuration, but do not have a
-- media_url yet. Do not schedule/send them as documents until a real URL
-- is supplied. Text templates are usable for initial scheduler testing.
-- ===========================================================

INSERT INTO templates (
    template_code, template_name, message_type, message_content, language
) VALUES
    (
        'WEIGHT_REMINDER', 'Daily Weight Reminder', 'TEXT',
        'Good morning, {{member_name}}! When you are ready, please share a quick photo of your scale screen.',
        'en'
    ),
    (
        'FOUNDATION_LUNCH_GUIDE', 'Foundation Lunch Guide', 'TEXT',
        'Here is your nourishing lunch recommendation, {{member_name}}! Enjoy your meal.',
        'en'
    ),
    (
        'FOUNDATION_GREENS_NUDGE', 'Weekly Greens Nudge', 'TEXT',
        'Happy Saturday! Here are some fresh, nourishing greens to consider for your shopping list.',
        'en'
    ),
    (
        'PARAMETER_DIGEST', 'Weekly Body Parameter Feedback', 'TEXT',
        'Hi {{member_name}}! Let us take a moment to appreciate your consistency and progress this week.',
        'en'
    ),
    (
        'FOUNDATION_MONTHLY_PLAN', 'Foundation Monthly Meal Plan Roadmap', 'DOCUMENT',
        'Your monthly meal plan roadmap is ready, {{member_name}}!',
        'en'
    ),
    (
        'PRO_HYDRATION', 'Pro Hourly Hydration Reminder', 'TEXT',
        'Hourly hydration check, {{member_name}}! Time for your glass of water. Sip and thrive!',
        'en'
    ),
    (
        'PRO_BREAKFAST', 'Pro Breakfast Reminder', 'TEXT',
        'Good morning, {{member_name}}! Your breakfast reminder is here.',
        'en'
    ),
    (
        'PRO_LUNCH', 'Pro Lunch Guide', 'TEXT',
        'Time to refuel, {{member_name}}! Your lunch guide is ready.',
        'en'
    ),
    (
        'PRO_PREP_NUDGE', 'Pro Next-Day Prep Nudge', 'TEXT',
        'A little preparation tonight can make tomorrow easier, {{member_name}}.',
        'en'
    ),
    (
        'PRO_SLEEP_WIND_DOWN', 'Pro Sleep Wind Down', 'TEXT',
        'Hi {{member_name}}! It is time to start winding down for a restful night.',
        'en'
    ),
    (
        'PRO_FORTNIGHTLY_PLAN', 'Pro Fortnightly Meal Plan', 'DOCUMENT',
        'Your bi-weekly meal plan is ready, {{member_name}}!',
        'en'
    ),
    (
        'MAX_HYDRATION', 'Max Hourly Hydration Reminder', 'TEXT',
        'Hourly sip check, {{member_name}}! Take a gentle sip of water and keep your habit going.',
        'en'
    ),
    (
        'MAX_WEEKLY_PLAN', 'Max Weekly Custom Meal Plan', 'DOCUMENT',
        'Your custom weekly meal plan is ready, {{member_name}}!',
        'en'
    ),
    (
        'ULTRA_HYDRATION', 'Ultra Hourly Hydration Reminder', 'TEXT',
        'Hourly concierge hydration sync, {{member_name}}! Take a refreshing sip from your desk flask.',
        'en'
    ),
    (
        'ULTRA_WEEKLY_PLAN', 'Ultra Executive Meal Plan', 'DOCUMENT',
        'Your executive weekly culinary roadmap is ready, {{member_name}}!',
        'en'
    ),
    (
        'ULTRA_MAID_PREP_CARD', 'Ultra Family/Maid Preparation Card', 'DOCUMENT',
        'Preparation card for tomorrow for {{member_name}}. Attach the approved meal/preparation document before production use.',
        'en'
    );


-- ============================================================
-- INITIAL MESSAGE SCHEDULES
-- Schedule types and columns use only the final schema.
-- Monthly plan-cycle schedules are intentionally not seeded because this
-- final schema does not have a monthly recurrence type or plan-start date.
-- Document-based schedules are not seeded until media_url values exist.
-- ============================================================

-- Foundation: daily weight reminder at 07:00.
INSERT INTO message_schedules (
    tier_id, phase_id, day_offset, task_type, template_id, schedule_type, send_time
)
SELECT t.tier_id, NULL, NULL, 'WEIGHT_REMINDER', tp.template_id, 'DAILY', '07:00'
FROM tiers t
JOIN templates tp ON tp.template_code = 'WEIGHT_REMINDER'
WHERE t.tier_name = 'Foundation';

-- Foundation: daily lunch guide at 12:30.
INSERT INTO message_schedules (
    tier_id, phase_id, day_offset, task_type, template_id, schedule_type, send_time
)
SELECT t.tier_id, NULL, NULL, 'LUNCH_GUIDE', tp.template_id, 'DAILY', '12:30'
FROM tiers t
JOIN templates tp ON tp.template_code = 'FOUNDATION_LUNCH_GUIDE'
WHERE t.tier_name = 'Foundation';

-- Foundation: Saturday greens nudge at 10:00 (Saturday = 6).
INSERT INTO message_schedules (
    tier_id, phase_id, task_type, template_id, schedule_type, send_time, day_of_week
)
SELECT t.tier_id, NULL, 'GREENS_NUDGE', tp.template_id, 'WEEKLY', '10:00', 6
FROM tiers t
JOIN templates tp ON tp.template_code = 'FOUNDATION_GREENS_NUDGE'
WHERE t.tier_name = 'Foundation';

-- Foundation: Saturday parameter digest at 17:00.
INSERT INTO message_schedules (
    tier_id, phase_id, task_type, template_id, schedule_type, send_time, day_of_week
)
SELECT t.tier_id, NULL, 'PARAMETER_DIGEST', tp.template_id, 'WEEKLY', '17:00', 6
FROM tiers t
JOIN templates tp ON tp.template_code = 'PARAMETER_DIGEST'
WHERE t.tier_name = 'Foundation';

-- Pro: daily weight check at 07:00.
INSERT INTO message_schedules (
    tier_id, phase_id, task_type, template_id, schedule_type, send_time
)
SELECT t.tier_id, NULL, 'WEIGHT_REMINDER', tp.template_id, 'DAILY', '07:00'
FROM tiers t
JOIN templates tp ON tp.template_code = 'WEIGHT_REMINDER'
WHERE t.tier_name = 'Pro';

-- Pro: hourly hydration from 08:00 through 20:00 inclusive.
INSERT INTO message_schedules (
    tier_id, phase_id, task_type, template_id, schedule_type,
    start_time, end_time, interval_minutes
)
SELECT t.tier_id, NULL, 'HYDRATION_REMINDER', tp.template_id, 'HOURLY',
       '08:00', '20:00', 60
FROM tiers t
JOIN templates tp ON tp.template_code = 'PRO_HYDRATION'
WHERE t.tier_name = 'Pro';

-- Pro: breakfast, lunch, preparation and sleep reminders.
INSERT INTO message_schedules (
    tier_id, phase_id, task_type, template_id, schedule_type, send_time
)
SELECT t.tier_id, NULL, v.task_type, tp.template_id, 'DAILY', v.send_time
FROM tiers t
JOIN (VALUES
    ('BREAKFAST_REMINDER', 'PRO_BREAKFAST',       TIME '08:00'),
    ('LUNCH_GUIDE',        'PRO_LUNCH',           TIME '13:00'),
    ('PREP_NUDGE',         'PRO_PREP_NUDGE',      TIME '19:00'),
    ('SLEEP_WIND_DOWN',    'PRO_SLEEP_WIND_DOWN', TIME '22:00')
) AS v(task_type, template_code, send_time) ON TRUE
JOIN templates tp ON tp.template_code = v.template_code
WHERE t.tier_name = 'Pro';

-- Max: hourly hydration from 08:00 through 20:00 inclusive.
INSERT INTO message_schedules (
    tier_id, phase_id, task_type, template_id, schedule_type,
    start_time, end_time, interval_minutes
)
SELECT t.tier_id, NULL, 'HYDRATION_REMINDER', tp.template_id, 'HOURLY',
       '08:00', '20:00', 60
FROM tiers t
JOIN templates tp ON tp.template_code = 'MAX_HYDRATION'
WHERE t.tier_name = 'Max';

-- Ultra: hourly hydration from 08:00 through 20:00 inclusive.
INSERT INTO message_schedules (
    tier_id, phase_id, task_type, template_id, schedule_type,
    start_time, end_time, interval_minutes
)
SELECT t.tier_id, NULL, 'HYDRATION_REMINDER', tp.template_id, 'HOURLY',
       '08:00', '20:00', 60
FROM tiers t
JOIN templates tp ON tp.template_code = 'ULTRA_HYDRATION'
WHERE t.tier_name = 'Ultra';


-- ============================================================
-- TEST MEMBERS
-- These are test profiles, not real customer records.
-- Faizan: Pro, currently in P1 for scheduler testing.
-- Zyve Test User: Max, currently in P2 for different-tier testing.
-- The assignments are test assumptions and can be changed in the DB.
-- ============================================================

INSERT INTO members (
    member_code, member_name, phone_number, whatsapp_sender_id,
    joining_date, tier_id, phase_id
)
VALUES
(
    'TEST_FAIZAN', 'Faizan', NULL, NULL,
    CURRENT_DATE - 4,
    (SELECT tier_id FROM tiers WHERE tier_name = 'Pro'),
    (SELECT phase_id FROM phases WHERE phase_name = 'P1')
),
(
    'TEST_AHAD', 'Ahad', NULL, NULL,
    CURRENT_DATE - 4,
    (SELECT tier_id FROM tiers WHERE tier_name = 'Ultra'),
    (SELECT phase_id FROM phases WHERE phase_name = 'P1')
),
(
    'TEST_ZYVE_USER', 'Zyve Test User', NULL, NULL,
    CURRENT_DATE - 14,
    (SELECT tier_id FROM tiers WHERE tier_name = 'Max'),
    (SELECT phase_id FROM phases WHERE phase_name = 'P2')
);



-- ============================================================
-- TEST CHAT ROUTES
-- The two group IDs are actual supplied test IDs.
-- 'xxxx@c.us' is a placeholder and is deliberately not linked below.
-- ============================================================

INSERT INTO whatsapp_groups (periskope_chat_id, group_name)
VALUES
    ('918948937671@c.us', 'Ahad Individual Chat - PLACEHOLDER NOT LINKED'),
    ('120363412042215031@g.us', 'Dev Test Group 01'),
    ('120363431222993492@g.us', 'Multi Membership holder test'),
    ('919674671233@c.us', 'Faizan Individual Chat - PLACEHOLDER NOT LINKED');


-- ============================================================
-- TEST GROUP MEMBERSHIPS
-- Both Faizan and Zyve Test User are in both test groups.
-- ============================================================

INSERT INTO group_members (group_id, member_id)
VALUES
    (
        (SELECT group_id FROM whatsapp_groups
         WHERE periskope_chat_id = '120363412042215031@g.us'),
        (SELECT member_id FROM members WHERE member_code = 'TEST_AHAD')
    ),
    (
        (SELECT group_id FROM whatsapp_groups
         WHERE periskope_chat_id = '120363412042215031@g.us'),
        (SELECT member_id FROM members WHERE member_code = 'TEST_FAIZAN')
    ),
    (
        (SELECT group_id FROM whatsapp_groups
         WHERE periskope_chat_id = '120363412042215031@g.us'),
        (SELECT member_id FROM members WHERE member_code = 'TEST_ZYVE_USER')
    ),
    (
        (SELECT group_id FROM whatsapp_groups
         WHERE periskope_chat_id = '120363431222993492@g.us'),
        (SELECT member_id FROM members WHERE member_code = 'TEST_FAIZAN')
    ),
    (
        (SELECT group_id FROM whatsapp_groups
         WHERE periskope_chat_id = '120363431222993492@g.us'),
        (SELECT member_id FROM members WHERE member_code = 'TEST_ZYVE_USER')
    );


-- ============================================================
-- QUICK VERIFICATION QUERIES
-- ============================================================

-- Confirm the two test groups and their linked members.
-- SELECT wg.group_name, wg.periskope_chat_id, m.member_code, m.member_name,
--        t.tier_name, p.phase_name
-- FROM whatsapp_groups wg
-- JOIN group_members gm ON gm.group_id = wg.group_id
-- JOIN members m ON m.member_id = gm.member_id
-- LEFT JOIN tiers t ON t.tier_id = m.tier_id
-- LEFT JOIN phases p ON p.phase_id = m.phase_id
-- WHERE wg.periskope_chat_id IN (
--     '120363412042215031@g.us',
--     '120363431222993492@g.us'
-- )
-- ORDER BY wg.group_name, m.member_name;

COMMIT;

-- ============================================================
-- NOTES FOR THE OUTGOING SCHEDULER
-- 1. With both memberships active, each member resolves to BOTH groups.
--    Do not perform a live send until the dry-run destinations are checked.
-- 2. Replace 'xxxx@c.us' with Faizan's real individual chat ID, then add
--    a group_members row to link it when you intentionally want to test DMs.
-- 3. Do not use the seeded DOCUMENT templates for live sends until media_url
--    is populated with a valid document URL. They are not scheduled above.
-- 4. The final schema doesn't support monthly plan-cycle recurrence. We have
--    intentionally not inserted a monthly recurrence row or added columns.
-- ============================================================


BEGIN;

-- 1. Ensure the four service tiers exist.
INSERT INTO tiers (tier_name, description)
VALUES
    ('Foundation', 'Tier 1 - Self-Guided'),
    ('Pro',        'Tier 2 - Rigid Metabolic'),
    ('Max',        'Tier 3 - Autopilot Habit'),
    ('Ultra',      'Tier 4 - White-Glove Concierge')
ON CONFLICT DO NOTHING;

-- 2. Ensure initial phases exist.
INSERT INTO phases (
    phase_name, phase_number, start_day, end_day, description
)
VALUES
    ('P1', 1, 1,   10,   'Initial phase'),
    ('P2', 2, 11,  20,   'Early progression phase'),
    ('P3', 3, 21,  40,   'Intermediate progression phase'),
    ('P4', 4, 41,  60,   'Advanced progression phase'),
    ('P5', 5, 61,  9999, 'Long-term progression phase')
ON CONFLICT DO NOTHING;

-- 3. Link existing test members to test tier/phase assignments.
-- These are test assignments, not production customer assignments.
UPDATE members AS m
SET tier_id = t.tier_id,
    phase_id = p.phase_id,
    updated_at = CURRENT_TIMESTAMP
FROM tiers AS t, phases AS p
WHERE m.member_code = 'TEST_FAIZAN'
  AND t.tier_name = 'Pro'
  AND p.phase_name = 'P1';

UPDATE members AS m
SET tier_id = t.tier_id,
    phase_id = p.phase_id,
    updated_at = CURRENT_TIMESTAMP
FROM tiers AS t, phases AS p
WHERE m.member_code = 'TEST_ZYVE_USER'
  AND t.tier_name = 'Max'
  AND p.phase_name = 'P2';

-- 4. Restore representative schedule rows.
-- These were missed if the original seed ran before tiers existed,
-- because its INSERT ... SELECT statements then selected zero rows.
-- Document templates are deliberately not scheduled without media URLs.

-- Foundation: daily weight reminder at 07:00.
INSERT INTO message_schedules
    (tier_id, phase_id, day_offset, task_type, template_id, schedule_type, send_time)
SELECT t.tier_id, NULL, NULL, 'WEIGHT_REMINDER', tp.template_id, 'DAILY', TIME '07:00'
FROM tiers t
JOIN templates tp ON tp.template_code = 'WEIGHT_REMINDER'
WHERE t.tier_name = 'Foundation'
  AND NOT EXISTS (
      SELECT 1 FROM message_schedules ms
      WHERE ms.tier_id = t.tier_id AND ms.phase_id IS NULL
        AND ms.task_type = 'WEIGHT_REMINDER' AND ms.template_id = tp.template_id
        AND ms.schedule_type = 'DAILY' AND ms.send_time = TIME '07:00'
  );

-- Foundation: daily lunch guide at 12:30.
INSERT INTO message_schedules
    (tier_id, phase_id, day_offset, task_type, template_id, schedule_type, send_time)
SELECT t.tier_id, NULL, NULL, 'LUNCH_GUIDE', tp.template_id, 'DAILY', TIME '12:30'
FROM tiers t
JOIN templates tp ON tp.template_code = 'FOUNDATION_LUNCH_GUIDE'
WHERE t.tier_name = 'Foundation'
  AND NOT EXISTS (
      SELECT 1 FROM message_schedules ms
      WHERE ms.tier_id = t.tier_id AND ms.phase_id IS NULL
        AND ms.task_type = 'LUNCH_GUIDE' AND ms.template_id = tp.template_id
        AND ms.schedule_type = 'DAILY' AND ms.send_time = TIME '12:30'
  );

-- Foundation: Saturday greens nudge at 10:00 (Saturday = 6).
INSERT INTO message_schedules
    (tier_id, phase_id, task_type, template_id, schedule_type, send_time, day_of_week)
SELECT t.tier_id, NULL, 'GREENS_NUDGE', tp.template_id, 'WEEKLY', TIME '10:00', 6
FROM tiers t
JOIN templates tp ON tp.template_code = 'FOUNDATION_GREENS_NUDGE'
WHERE t.tier_name = 'Foundation'
  AND NOT EXISTS (
      SELECT 1 FROM message_schedules ms
      WHERE ms.tier_id = t.tier_id AND ms.phase_id IS NULL
        AND ms.task_type = 'GREENS_NUDGE' AND ms.template_id = tp.template_id
        AND ms.schedule_type = 'WEEKLY' AND ms.send_time = TIME '10:00'
        AND ms.day_of_week = 6
  );

-- Foundation: Saturday parameter digest at 17:00.
INSERT INTO message_schedules
    (tier_id, phase_id, task_type, template_id, schedule_type, send_time, day_of_week)
SELECT t.tier_id, NULL, 'PARAMETER_DIGEST', tp.template_id, 'WEEKLY', TIME '17:00', 6
FROM tiers t
JOIN templates tp ON tp.template_code = 'PARAMETER_DIGEST'
WHERE t.tier_name = 'Foundation'
  AND NOT EXISTS (
      SELECT 1 FROM message_schedules ms
      WHERE ms.tier_id = t.tier_id AND ms.phase_id IS NULL
        AND ms.task_type = 'PARAMETER_DIGEST' AND ms.template_id = tp.template_id
        AND ms.schedule_type = 'WEEKLY' AND ms.send_time = TIME '17:00'
        AND ms.day_of_week = 6
  );

-- Pro: daily weight reminder at 07:00.
INSERT INTO message_schedules
    (tier_id, phase_id, task_type, template_id, schedule_type, send_time)
SELECT t.tier_id, NULL, 'WEIGHT_REMINDER', tp.template_id, 'DAILY', TIME '07:00'
FROM tiers t
JOIN templates tp ON tp.template_code = 'WEIGHT_REMINDER'
WHERE t.tier_name = 'Pro'
  AND NOT EXISTS (
      SELECT 1 FROM message_schedules ms
      WHERE ms.tier_id = t.tier_id AND ms.phase_id IS NULL
        AND ms.task_type = 'WEIGHT_REMINDER' AND ms.template_id = tp.template_id
        AND ms.schedule_type = 'DAILY' AND ms.send_time = TIME '07:00'
  );

-- Pro: hourly hydration 08:00 through 20:00 inclusive.
INSERT INTO message_schedules
    (tier_id, phase_id, task_type, template_id, schedule_type, start_time, end_time, interval_minutes)
SELECT t.tier_id, NULL, 'HYDRATION_REMINDER', tp.template_id, 'HOURLY', TIME '08:00', TIME '20:00', 60
FROM tiers t
JOIN templates tp ON tp.template_code = 'PRO_HYDRATION'
WHERE t.tier_name = 'Pro'
  AND NOT EXISTS (
      SELECT 1 FROM message_schedules ms
      WHERE ms.tier_id = t.tier_id AND ms.phase_id IS NULL
        AND ms.task_type = 'HYDRATION_REMINDER' AND ms.template_id = tp.template_id
        AND ms.schedule_type = 'HOURLY' AND ms.start_time = TIME '08:00'
        AND ms.end_time = TIME '20:00' AND ms.interval_minutes = 60
  );

-- Pro: breakfast, lunch, prep nudge, and sleep wind-down.
INSERT INTO message_schedules
    (tier_id, phase_id, task_type, template_id, schedule_type, send_time)
SELECT t.tier_id, NULL, v.task_type, tp.template_id, 'DAILY', v.send_time
FROM tiers t
CROSS JOIN (VALUES
    ('BREAKFAST_REMINDER', 'PRO_BREAKFAST',       TIME '08:00'),
    ('LUNCH_GUIDE',        'PRO_LUNCH',           TIME '13:00'),
    ('PREP_NUDGE',         'PRO_PREP_NUDGE',      TIME '19:00'),
    ('SLEEP_WIND_DOWN',    'PRO_SLEEP_WIND_DOWN', TIME '22:00')
) AS v(task_type, template_code, send_time)
JOIN templates tp ON tp.template_code = v.template_code
WHERE t.tier_name = 'Pro'
  AND NOT EXISTS (
      SELECT 1 FROM message_schedules ms
      WHERE ms.tier_id = t.tier_id AND ms.phase_id IS NULL
        AND ms.task_type = v.task_type AND ms.template_id = tp.template_id
        AND ms.schedule_type = 'DAILY' AND ms.send_time = v.send_time
  );

-- Max: hourly hydration 08:00 through 20:00 inclusive.
INSERT INTO message_schedules
    (tier_id, phase_id, task_type, template_id, schedule_type, start_time, end_time, interval_minutes)
SELECT t.tier_id, NULL, 'HYDRATION_REMINDER', tp.template_id, 'HOURLY', TIME '08:00', TIME '20:00', 60
FROM tiers t
JOIN templates tp ON tp.template_code = 'MAX_HYDRATION'
WHERE t.tier_name = 'Max'
  AND NOT EXISTS (
      SELECT 1 FROM message_schedules ms
      WHERE ms.tier_id = t.tier_id AND ms.phase_id IS NULL
        AND ms.task_type = 'HYDRATION_REMINDER' AND ms.template_id = tp.template_id
        AND ms.schedule_type = 'HOURLY' AND ms.start_time = TIME '08:00'
        AND ms.end_time = TIME '20:00' AND ms.interval_minutes = 60
  );

-- Ultra: hourly hydration 08:00 through 20:00 inclusive.
INSERT INTO message_schedules
    (tier_id, phase_id, task_type, template_id, schedule_type, start_time, end_time, interval_minutes)
SELECT t.tier_id, NULL, 'HYDRATION_REMINDER', tp.template_id, 'HOURLY', TIME '08:00', TIME '20:00', 60
FROM tiers t
JOIN templates tp ON tp.template_code = 'ULTRA_HYDRATION'
WHERE t.tier_name = 'Ultra'
  AND NOT EXISTS (
      SELECT 1 FROM message_schedules ms
      WHERE ms.tier_id = t.tier_id AND ms.phase_id IS NULL
        AND ms.task_type = 'HYDRATION_REMINDER' AND ms.template_id = tp.template_id
        AND ms.schedule_type = 'HOURLY' AND ms.start_time = TIME '08:00'
        AND ms.end_time = TIME '20:00' AND ms.interval_minutes = 60
  );

COMMIT;

-- ============================================================
-- VERIFICATION 1: tier and phase master data
-- ============================================================
SELECT tier_id, tier_name FROM tiers ORDER BY tier_id;

SELECT phase_id, phase_name, phase_number, start_day, end_day
FROM phases ORDER BY phase_number;

-- ============================================================
-- VERIFICATION 2: intended test member assignments
-- ============================================================
SELECT
    m.member_code,
    m.member_name,
    m.tier_id,
    t.tier_name,
    m.phase_id,
    p.phase_name
FROM members m
LEFT JOIN tiers t ON t.tier_id = m.tier_id
LEFT JOIN phases p ON p.phase_id = m.phase_id
WHERE m.member_code IN ('TEST_FAIZAN', 'TEST_ZYVE_USER')
ORDER BY m.member_code;

-- ============================================================
-- VERIFICATION 3: group membership and names (expected four rows)
-- ============================================================
SELECT
    wg.group_name,
    wg.periskope_chat_id,
    m.member_code,
    m.member_name,
    t.tier_name,
    p.phase_name
FROM whatsapp_groups wg
JOIN group_members gm ON gm.group_id = wg.group_id
JOIN members m ON m.member_id = gm.member_id
LEFT JOIN tiers t ON t.tier_id = m.tier_id
LEFT JOIN phases p ON p.phase_id = m.phase_id
WHERE wg.periskope_chat_id IN (
    '120363412042215031@g.us',
    '120363431222993492@g.us'
)
ORDER BY wg.group_name, m.member_name;

-- ============================================================
-- VERIFICATION 4: rows available for outgoing scheduler testing
-- ============================================================
SELECT
    ms.schedule_id,
    t.tier_name,
    ms.task_type,
    ms.schedule_type,
    ms.send_time,
    ms.start_time,
    ms.end_time,
    ms.interval_minutes,
    tp.template_code
FROM message_schedules ms
JOIN tiers t ON t.tier_id = ms.tier_id
JOIN templates tp ON tp.template_id = ms.template_id
ORDER BY t.tier_name, ms.schedule_id;
