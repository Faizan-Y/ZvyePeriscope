-- ============================================================
-- ZYVEFIT WHATSAPP AUTOMATION - CONSOLIDATED DATA LOAD (ALL INSERTS)
-- ============================================================
--
-- This is the ONLY SQL file with INSERT statements. It contains all
-- seed/master data for the Zyvefit WhatsApp automation:
--   1. tiers             4 rows
--   2. phases            5 rows
--   3. templates         83 rows (this file is the source of truth for message content)
--   4. message_schedules 38 rows (current runtime values)
--   5. members           test profiles
--   6. whatsapp_groups   test routes
--   7. group_members     test memberships
--
-- RUN ORDER: run zvyefit_v81_templates.sql FIRST (table creations),
-- then run this file.
--
-- RE-RUN SAFETY (idempotent, never destructive):
--   * Re-running never deletes, deactivates, or re-activates anything.
--   * Templates upsert: content is refreshed from this file; media_url
--     is intentionally NOT updated (operator-managed in the DB).
--   * Schedules / members / groups: insert-only when the exact row is
--     missing. is_active changes made directly in the DB are never
--     reverted by this file.
--   * message_logs / incoming_messages are runtime tables and are
--     never seeded.
--
-- CURRENT STATE BAKED IN (as of 2026-10-17):
--   * Sleep wind-down / habit-audit send_time is 21:00 (was 22:00).
--   * HOURLY hydration windows are 08:00-20:00 per the playbook.
--   * phase_id is NOT NULL: every schedule and every member is pinned
--     to P1 until phase-wise scheduling is introduced.
--   * All 38 schedules are seeded active.
--
-- KNOWN DEFERRED ISSUES (production audit - fix later, kept as-is):
--   * Schedules 30 / 31 / 36 / 38: DOCUMENT templates with no media_url
--     yet; they print [NOT READY] and never send until a URL is added.
--   * Schedules 35 / 37 / 38: unresolved placeholders (neural_audio_link,
--     spouse_name); they print [CONFIG ERROR] and never send.
--   * Members advancing beyond P1 stop matching these P1 rules until
--     phase-wise schedules exist.
--   * day_of_month is unused by every schedule and is omitted below.
-- ============================================================

BEGIN;

-- ============================================================
-- 1. TIERS
-- ============================================================
INSERT INTO tiers (tier_name, description)
VALUES
    ('Foundation', 'Tier 1 - Self-Guided'),
    ('Pro', 'Tier 2 - Rigid Metabolic'),
    ('Max', 'Tier 3 - Autopilot Habit'),
    ('Ultra', 'Tier 4 - White-Glove Concierge')
ON CONFLICT (tier_name) DO NOTHING;

-- ============================================================
-- 2. PHASES
-- ============================================================
INSERT INTO phases (phase_name, phase_number, start_day, end_day, description)
VALUES
    ('P1', 1, 1, 10, 'Initial phase'),
    ('P2', 2, 11, 20, 'Early progression phase'),
    ('P3', 3, 21, 40, 'Intermediate progression phase'),
    ('P4', 4, 41, 60, 'Advanced progression phase'),
    ('P5', 5, 61, 9999, 'Long-term progression phase')
ON CONFLICT (phase_name) DO NOTHING;

-- ============================================================
-- 3. TEMPLATES (full catalog)
-- media_url is inserted only for brand-new rows; on conflict it is
-- deliberately NOT updated, so operator-managed URLs survive re-runs.
-- ============================================================
INSERT INTO templates (template_code, template_name, message_type, message_content, media_url, language)
VALUES
    ('WEIGHT_REMINDER', 'Daily Weight Reminder', 'TEXT', 'Good morning, {{member_name}}! When you are ready, please share a quick photo of your scale screen.', NULL, 'en'),
    ('FOUNDATION_LUNCH_GUIDE', 'Foundation Lunch Guide', 'TEXT', 'Here is your nourishing lunch recommendation, {{member_name}}! Enjoy your meal.', NULL, 'en'),
    ('FOUNDATION_GREENS_NUDGE', 'Weekly Greens Nudge', 'TEXT', 'Happy Saturday! Here are some fresh, nourishing greens to consider for your shopping list.', NULL, 'en'),
    ('PARAMETER_DIGEST', 'Weekly Body Parameter Feedback', 'TEXT', 'Hi {{member_name}}! Let us take a moment to appreciate your consistency and progress this week.', NULL, 'en'),
    ('FOUNDATION_MONTHLY_PLAN', 'Foundation Monthly Meal Plan Roadmap', 'DOCUMENT', 'Your monthly meal plan roadmap is ready, {{member_name}}!', NULL, 'en'),
    ('PRO_HYDRATION', 'Pro Hourly Hydration Reminder', 'TEXT', 'Hourly hydration check, {{member_name}}! Time for your glass of water. Sip and thrive!', NULL, 'en'),
    ('PRO_BREAKFAST', 'Pro Breakfast Reminder', 'TEXT', 'Good morning, {{member_name}}! Your breakfast reminder is here.', NULL, 'en'),
    ('PRO_LUNCH', 'Pro Lunch Guide', 'TEXT', 'Time to refuel, {{member_name}}! Your lunch guide is ready.', NULL, 'en'),
    ('PRO_PREP_NUDGE', 'Pro Next-Day Prep Nudge', 'TEXT', 'A little preparation tonight can make tomorrow easier, {{member_name}}.', NULL, 'en'),
    ('PRO_SLEEP_WIND_DOWN', 'Pro Sleep Wind Down', 'TEXT', 'Hi {{member_name}}! It is time to start winding down for a restful night.', NULL, 'en'),
    ('PRO_FORTNIGHTLY_PLAN', 'Pro Fortnightly Meal Plan', 'DOCUMENT', 'Your bi-weekly meal plan is ready, {{member_name}}!', NULL, 'en'),
    ('MAX_HYDRATION', 'Max Hourly Hydration Reminder', 'TEXT', 'Hourly sip check, {{member_name}}! Take a gentle sip of water and keep your habit going.', NULL, 'en'),
    ('MAX_WEEKLY_PLAN', 'Max Weekly Custom Meal Plan', 'DOCUMENT', 'Your custom weekly meal plan is ready, {{member_name}}!', NULL, 'en'),
    ('ULTRA_HYDRATION', 'Ultra Hourly Hydration Reminder', 'TEXT', 'Hourly concierge hydration sync, {{member_name}}! Take a refreshing sip from your desk flask.', NULL, 'en'),
    ('ULTRA_WEEKLY_PLAN', 'Ultra Executive Meal Plan', 'DOCUMENT', 'Your executive weekly culinary roadmap is ready, {{member_name}}!', NULL, 'en'),
    ('ULTRA_MAID_PREP_CARD', 'Ultra Family/Maid Preparation Card', 'DOCUMENT', 'Preparation card for tomorrow for {{member_name}}. Attach the approved meal/preparation document before production use.', NULL, 'en'),
    ('FOUNDATION_WAKE_UP_SCALE_READING', 'Wake-up & Scale Reading', 'TEXT', 'Good morning, {{first_name}}! 🌅 Sending you a warm, gentle start to your day. Let''s take a loving check-in with your body—whenever you are ready, please share a quick photo of your scale''s screen right here. We are right here with you!', NULL, 'en'),
    ('FOUNDATION_MONTHLY_MEAL_PLAN_ROADMAP_DELIVERY', 'Monthly Meal Plan Roadmap Delivery', 'DOCUMENT', 'Here is your monthly nourishing meal roadmap, {{first_name}}! 🍲 Designed to give you clear, gentle structure for the month ahead while honoring your personal lifestyle pace. Whenever you''re ready, dive in and let this fuel your wellbeing!', NULL, 'en'),
    ('FOUNDATION_NOURISHING_LUNCH_GUIDE', 'Nourishing Lunch Guide', 'TEXT', 'Here is your nourishing lunch recommendation, {{first_name}}! 🍲 Balanced gently to keep your energy steady today. Enjoy your meal!', NULL, 'en'),
    ('FOUNDATION_WEEKLY_GROCERY_STOCK_UP', 'Weekly Grocery Stock-up', 'TEXT', E'Happy Saturday, {{First Name}}!\n If you are heading out for groceries today, make sure to stock up on your fresh vegetables and plan essentials for the week ahead. Having a well-stocked kitchen is your best safety net for staying consistent!', NULL, 'en'),
    ('FOUNDATION_WEEKLY_BODY_PARAMETER_FEEDBACK', 'Weekly Body Parameter Feedback', 'TEXT', 'Hi {{first_name}}! 🌸 As we wrap up the week, let''s take a warm moment to appreciate your body''s journey. Your scale trends show gentle, beautiful progress in your body parameters. We are so incredibly proud of your consistency. Thank you for trusting us with your health—it is 100% our passion to support you!', NULL, 'en'),
    ('FOUNDATION_RENEWAL_VALUE_NUDGE', 'Renewal Value Nudge', 'TEXT', 'Hello, {{first_name}}! 🌟 We are so honored to support your health. Just a gentle, caring note that your auto-renewal is coming up on {{renewal_date}}. We are so excited to keep walking this path of wellness with you!', NULL, 'en'),
    ('FOUNDATION_PLAN_EXPIRY_ALERT', 'Plan Expiry Alert', 'TEXT', 'Hi {{first_name}}, just a gentle, warm heads-up! ⏰ Your current plan path comes to a close tomorrow. To keep your daily meal guides flowing smoothly, you can easily renew here: {{direct_payment_link}}.', NULL, 'en'),
    ('FOUNDATION_ACCOUNT_HOLD_NOTICE', 'Account Hold Notice', 'TEXT', 'Hi {{first_name}}! ⏸️ Your active plan guides are on a gentle, restful pause. Your historical scale data, logs, and meal records are stored safely in our hearts and system. Whenever you''re ready to jump back in, we are right here to welcome you with open arms.', NULL, 'en'),
    ('PRO_WAKE_UP_SCALE_READING', 'Wake-up & Scale Reading', 'TEXT', 'Good morning, {{first_name}}! 🌅 Sending you a warm, gentle start to your day. Let''s take a loving check-in with your body—whenever you are ready, please share a quick photo of your scale''s screen right here. We are right here with you!', NULL, 'en'),
    ('PRO_ACTIVITY_CUE_BRANCH_A', 'Activity Cue (Branch A)', 'TEXT', 'Good morning, {{first_name}}! ⚡ Time for your planned morning movement. Please listen to your body and execute your session in a way that feels rewarding. Whenever you''re finished, let us know so we can send your breakfast guide!', NULL, 'en'),
    ('PRO_BREAKFAST_CUE_BRANCH_B', 'Breakfast Cue (Branch B)', 'TEXT', 'Time to nourish your beautiful cells, {{first_name}}! 🍳 Here is your precise fuel: **3 Egg whites, 40g Oats, and 1/2 avocado**. Enjoy every bite—your body will thank you for this structural balance and love!', NULL, 'en'),
    ('PRO_HOURLY_OSMOTIC_HYDRATION_CHECK', 'Hourly Osmotic Hydration Check', 'TEXT', 'Hourly Osmotic Hydration Check, {{first_name}}! 💧 Time for your hourly glass (~250ml) to keep your cellular enzymes active and mental focus sharp. Sip and thrive!', NULL, 'en'),
    ('PRO_FORTNIGHTLY_METABOLIC_MEAL_PLAN_DELIVERY', 'Fortnightly Metabolic Meal Plan Delivery', 'DOCUMENT', 'Your bi-weekly metabolic meal plan is ready, {{first_name}}! 🥗 Tailored with precision to keep your glycemic balance steady and your cellular energy high over the next 14 days. Let''s fuel your progress!', NULL, 'en'),
    ('PRO_MEAL_PLAN_REFINEMENT_ACKNOWLEDGEMENT', 'Meal Plan Refinement Acknowledgement', 'TEXT', 'Got it, {{first_name}}! 💬 We''ve received your meal plan adjustment request. Our coaching team is already recalibrating your macros and metabolic targets to match your needs. We''ll send your updated plan right over shortly!', NULL, 'en'),
    ('PRO_REFINED_MEAL_PLAN_DELIVERY', 'Refined Meal Plan Delivery', 'DOCUMENT', 'Here is your refined metabolic meal plan, {{first_name}}! 🎯 Updated with your requested adjustments while keeping your precision macro balance intact. Let''s keep your momentum going strong!', NULL, 'en'),
    ('PRO_NOURISHING_LUNCH_GUIDE', 'Nourishing Lunch Guide', 'TEXT', 'Time to refuel, {{first_name}}! 🥗 Your precise metabolic lunch is ready: **150g Grilled Chicken + 100g Jasmine Rice + 80g Asparagus**. Let this structural balance fuel your afternoon with steady focus and care!', NULL, 'en'),
    ('PRO_CLINICAL_SUPPLEMENT_REMINDER', 'Clinical Supplement Reminder', 'TEXT', 'A quick supplement reminder, {{first_name}}! 💊 Let''s support your thyroid and lipid profiles today: **1x Omega-3 + 1x Vitamin D3+K2**. Take a loving moment for yourself!', NULL, 'en'),
    ('PRO_NEXT_DAY_PREP_NUDGE', 'Next-Day Prep Nudge', 'TEXT', E'Set up for a peaceful tomorrow, {{First Name}}! \n Taking 10–15 minutes tonight to prep your scheduled meals and ingredients will make tomorrow completely effortless. Check your active meal plan and set yourself up for a smooth, nourishing day ahead!', NULL, 'en'),
    ('PRO_EVENING_SLEEP_WIND_DOWN', 'Evening Sleep Wind-down', 'TEXT', E'Time to rest and recharge, {{First Name}}! \n To support overnight recovery and metabolic balance, let''s power down screens and wind down for the night. Wishing you deep, peaceful sleep!', NULL, 'en'),
    ('PRO_WEEKLY_GROCERY_STOCK_UP', 'Weekly Grocery Stock-up', 'TEXT', E'Happy Saturday, {{First Name}}! \n If you are heading out for groceries today, make sure to stock up on your fresh vegetables and plan essentials for the week ahead. Having a well-stocked kitchen is your best safety net for staying consistent!', NULL, 'en'),
    ('PRO_WEEKLY_BODY_PARAMETER_FEEDBACK', 'Weekly Body Parameter Feedback', 'TEXT', 'Hello {{first_name}}! 🌸 Your end-of-week body parameter feedback is ready. Your clinical data shows steady metabolic alignment and lovely composition trends. Your dedication is inspiring, and we are honored to protect your health with precision!', NULL, 'en'),
    ('PRO_COACH_AUDIT_UPDATES', 'Coach Audit & Updates', 'TEXT', 'Hi {{first_name}}! 📈 Your 3-day metabolic update is ready. Your weight trend shows lovely glycemic stability, and water compliance hit 88%. Your coach has refined your targets to keep you thriving!', NULL, 'en'),
    ('PRO_1_1_COACHING_CHECK_IN', '1:1 Coaching Check-in', 'TEXT', 'Let''s connect, {{first_name}}! 🔬 It''s time for our fortnightly deep dive. Let''s schedule a 1:1 voice or video chat to celebrate your progress and adjust your plans: {{calendar_link}}', NULL, 'en'),
    ('PRO_RENEWAL_VALUE_NUDGE', 'Renewal Value Nudge', 'TEXT', 'Hello, {{first_name}}! 🌟 We are so honored to support your health. Just a gentle note that your auto-renewal is coming up on {{renewal_date}}. We are excited to keep walking this path with you!', NULL, 'en'),
    ('PRO_PLAN_EXPIRY_ALERT', 'Plan Expiry Alert', 'TEXT', 'Hi {{first_name}}, quick heads-up! ⏰ Your current plan path comes to a close tomorrow. To prevent your twice-weekly data reviews and custom meal guides from pausing, you can easily renew here: {{direct_payment_link}}.', NULL, 'en'),
    ('PRO_ACCOUNT_HOLD_NOTICE', 'Account Hold Notice', 'TEXT', 'Hi {{first_name}}! ⏸️ Your active plan guides are on a gentle pause. Your historical scale data, logs, and meal records are stored safely. Whenever you''re ready to jump back in, we are right here to welcome you.', NULL, 'en'),
    ('PRO_BLOOD_AUDIT_COLLECTION', 'Blood Audit Collection', 'TEXT', 'Biomarker Check-in, {{first_name}}! 🩸 To keep your metabolic plan perfectly aligned with your body, it is time for your pre-scheduled blood audit. Our partner lab will connect shortly to arrange sample collection.', NULL, 'en'),
    ('MAX_WAKE_UP_SCALE_READING', 'Wake-up & Scale Reading', 'TEXT', 'Good morning, {{first_name}}! 🌅 Sending you a warm, gentle start to your day. Let''s take a loving check-in with your body—whenever you are ready, please share a quick photo of your scale''s screen right here. We are right here with you!', NULL, 'en'),
    ('MAX_WORKOUT_NUDGE_MUSIC', 'Workout Nudge & Music', 'TEXT', '
Good morning, {{first_name}}! ☀️💪

*🎯 Your morning movement challenge*

Let''s kick-start your day with some joyful movement! Put on your favorite music, get moving, and enjoy the process. 🎶

🎧 *YOUR WORKOUT PLAYLIST*

🎵 *Spotify:*
https://open.spotify.com

▶️ *YouTube Music:*
https://music.youtube.com

🍎 Apple Music:
https://music.apple.com

✅ *Workout complete?*

Once you''ve finished, reply *DONE* in this chat so your coach knows you''re ready for the breakfast step. 🍳

Remember, consistency beats perfection. One small step at a time—you''ve got this! 🌟
', NULL, 'en'),
    ('MAX_BREAKFAST_CUE_SWAPS', 'Breakfast Cue (Swaps)', 'TEXT', 'Time to nourish, {{first_name}}! ☀️ Here is your custom breakfast: **3 Egg whites, 1 slice sourdough, 1/2 avocado**. If you''re on the move or need a gentle swap, just let us know—we''ve got options!', NULL, 'en'),
    ('MAX_HOURLY_HYDRATION_HABIT_LOOP', 'Hourly Hydration Habit Loop', 'TEXT', 'Hourly Sip Check-in, {{first_name}}! 🥤 A gentle splash of water this hour keeps your mind clear and your habit streak rolling. Keep your water bottle close!', NULL, 'en'),
    ('MAX_WEEKLY_CUSTOM_MEAL_PLAN_DELIVERY', 'Weekly Custom Meal Plan Delivery', 'DOCUMENT', 'Your custom weekly meal plan for the week ahead is here, {{first_name}}! 🥑 Carefully structured with your favorite active swaps and preferences. Check it out, and remember—we can always adjust together if your week shifts!', NULL, 'en'),
    ('MAX_MEAL_PLAN_REFINEMENT_ACKNOWLEDGEMENT', 'Meal Plan Refinement Acknowledgement', 'TEXT', 'No stress at all, {{first_name}}! 🌿 We love adjusting with you. Your change request is logged, and we''re modifying your swaps to make sure your meals fit your week effortlessly. Hang tight—your fresh plan is on its way!', NULL, 'en'),
    ('MAX_REFINED_MEAL_PLAN_DELIVERY', 'Refined Meal Plan Delivery', 'DOCUMENT', 'Your updated weekly meal plan is ready, {{first_name}}! ✨ Tailored around your fresh preferences so healthy eating feels completely peaceful and flexible. Take a look and let us know how it feels!', NULL, 'en'),
    ('MAX_NOURISHING_LUNCH_GUIDE', 'Nourishing Lunch Guide', 'TEXT', 'Nourishing lunch time, {{first_name}}! 🍽️ Here is your planned meal: **150g Grilled Chicken + 100g Jasmine Rice + Veggies**. If you don''t have this or need a warm swap, let us know—we can adjust together!', NULL, 'en'),
    ('MAX_MICRONUTRIENT_REMINDER', 'Micronutrient Reminder', 'TEXT', 'A friendly supplement check-in, {{first_name}}! 💊 Let''s keep your energy high and body strong: **1x Multivitamin + 1x Magnesium**. Take a quick moment for yourself!', NULL, 'en'),
    ('MAX_PREP_ACTIVE_SWAP_NUDGE', 'Prep & Active Swap Nudge', 'TEXT', E'Set up for a peaceful tomorrow, {{First Name}}! /n Taking 10–15 minutes tonight to prep your scheduled meals and ingredients will make tomorrow completely effortless. Check your active meal plan and set yourself up for a smooth, nourishing day ahead!', NULL, 'en'),
    ('MAX_DAILY_HABIT_AUDIT_CHECK_IN','Daily Habit Audit Check-in','TEXT', E'Time to rest and recharge, {{First Name}}! \n To support overnight recovery and metabolic balance, let''s power down screens and wind down for the night. Wishing you deep, peaceful sleep!', NULL, 'en'),
    ('MAX_GROCERY_STOCK_UP', 'Grocery Stock-up', 'TEXT', E'Happy Saturday, {{First Name}}! \n If you are heading out for groceries today, make sure to stock up on your fresh vegetables and plan essentials for the week ahead. Having a well-stocked kitchen is your best safety net for staying consistent!', NULL, 'en'),
    ('MAX_WEEKLY_BODY_PARAMETER_FEEDBACK', 'Weekly Body Parameter Feedback', 'TEXT', 'Happy Saturday, {{first_name}}! ✨ Your weekly body parameter review is ready. Your consistency score is amazing, and your body composition is aligning beautifully with your habit loops. You are doing fantastic, and we love celebrating every step of your progress!', NULL, 'en'),
    ('MAX_COACH_AUDIT_UPDATES', 'Coach Audit & Updates', 'TEXT', 'Hi {{first_name}}! 📈 Your 3-day log review is ready. Your consistency is amazing, and we love seeing your habit streak grow. Your coach has updated your targets to fit your busy week!', NULL, 'en'),
    ('MAX_1_1_COACHING_VOICE_SESSION', '1:1 Coaching Voice Session', 'TEXT', 'Time for our weekly check-in, {{first_name}}! 🗓️ Let''s look at your habit loops, scale patterns, and make sure your program flows beautifully with your busy life. Book your call here: {{calendar_link}}', NULL, 'en'),
    ('MAX_RENEWAL_VALUE_NUDGE', 'Renewal Value Nudge', 'TEXT', 'Hello, {{first_name}}! 🌟 We are so honored to support your health. Just a gentle note that your auto-renewal is coming up on {{renewal_date}}. We are excited to keep walking this path with you!', NULL, 'en'),
    ('MAX_PLAN_EXPIRY_ALERT', 'Plan Expiry Alert', 'TEXT', 'Hi {{first_name}}, quick heads-up! ⏰ Your current plan path comes to a close tomorrow. To keep your daily coach accountability, real-time swaps, and custom workouts active, you can easily renew here: {{direct_payment_link}}.', NULL, 'en'),
    ('MAX_ACCOUNT_HOLD_NOTICE', 'Account Hold Notice', 'TEXT', 'Hi {{first_name}}! ⏸️ Your active plan guides are on a gentle pause. Your historical scale data, logs, and meal records are stored safely. Whenever you''re ready to jump back in, we are right here to welcome you.', NULL, 'en'),
    ('MAX_BLOOD_AUDIT_COLLECTION', 'Blood Audit Collection', 'TEXT', 'Biomarker Check-in, {{first_name}}! 🩸 To keep your metabolic plan perfectly aligned with your body, it is time for your pre-scheduled blood audit. Our partner lab will connect shortly to arrange sample collection.', NULL, 'en'),
    ('ULTRA_WAKE_UP_SCALE_READING', 'Wake-up & Scale Reading', 'TEXT', 'Good morning, {{first_name}}! 🌅 Sending you a warm, gentle start to your day. Let''s take a loving check-in with your body—whenever you are ready, please share a quick photo of your scale''s screen right here. We are right here with you!', NULL, 'en'),
    ('ULTRA_MAID_PREP_CARD_DELIVERY', 'Maid Prep Card Delivery', 'DOCUMENT', 'Good evening, {{first_name}} / {{spouse_name}}! 🥂 To make tomorrow completely seamless and restful for {{first_name}}, here is their preparation card for tomorrow''s meals. Please forward this to your maid or cook:
*Akka, Anna, neenga kezale koduthulla breakfast matrum lunch ai prepare seiyya mudiyumaa?*
🍳 **Breakfast (08:30 AM):** *3 Egg whites + 1 whole egg omelette, 1 slice toasted brown bread, 1/2 avocado.*
🍽️ **Lunch (01:30 PM):** *150g chicken breast / paneer (dry/spray coconut oil), 100g cooked brown rice, one bowl boiled carrots/beans.*', NULL, 'en'),
    ('ULTRA_MAID_PREP_VERIFICATION', 'Maid Prep Verification', 'TEXT', 'A gentle morning greeting, {{first_name}} / {{spouse_name}}! ☀️ Just a quick check-in to make sure the morning breakfast and lunch preps are rolling smoothly for {{first_name}}. Let your concierge know if you need any adjustments!', NULL, 'en'),
    ('ULTRA_HOURLY_CONCIERGE_HYDRATION_SYNC', 'Hourly Concierge Hydration Sync', 'TEXT', 'Hourly Concierge Hydration Sync, {{first_name}}! 👑 Your hourly mineral-enhanced hydration check. Take a refreshing sip from your desk flask to maintain peak cellular vitality and executive focus!', NULL, 'en'),
    ('ULTRA_WEEKLY_EXECUTIVE_CONCIERGE_MEAL_PLAN_DELIVERY', 'Weekly Executive Concierge Meal Plan Delivery', 'DOCUMENT', 'Your executive weekly culinary roadmap is ready, {{first_name}}! 👑 Fully synchronized with your wearable metrics and pre-sent to your home chef. Relax knowing your biological support and gourmet preferences are completely taken care of!', NULL, 'en'),
    ('ULTRA_MEAL_PLAN_REFINEMENT_ACKNOWLEDGEMENT', 'Meal Plan Refinement Acknowledgement', 'TEXT', 'Consider it done, {{first_name}}! 👑 Your concierge team has accepted your meal plan adjustment request. We are updating your custom menu and notifying your kitchen chef right now. We''ll deliver your refined plan in just a few minutes!', NULL, 'en'),
    ('ULTRA_REFINED_MEAL_PLAN_DELIVERY', 'Refined Meal Plan Delivery', 'DOCUMENT', 'Your refined executive meal plan is complete, {{first_name}}! 🥂 Your new selections are seamlessly updated, and your preparation cards have been auto-synced with your home kitchen. Enjoy your tailored dining with total peace of mind!', NULL, 'en'),
    ('ULTRA_NOURISHING_LUNCH_GUIDE', 'Nourishing Lunch Guide', 'TEXT', 'Your home-cooked metabolic lunch is ready, {{first_name}}! 🥗 Balanced perfectly to keep you focused and energized all afternoon. Enjoy your peaceful, restful lunch break!', NULL, 'en'),
    ('ULTRA_CLINICAL_SUPPLEMENT_REMINDER', 'Clinical Supplement Reminder', 'TEXT', 'A gentle protocol reminder, {{first_name}}! 👑 Let''s execute your mid-day biological support: **1x CoQ10 + 1x Thyroid Support** pre-sorted in Tray B of your kit. We hope you''re having an amazing day!', NULL, 'en'),
    ('ULTRA_NEXT_DAY_PREP_STRATEGY_CARD','Next-Day Prep & Strategy Card', 'TEXT', E'Set up for a peaceful tomorrow, {{First Name}}! \n Taking 10–15 minutes tonight to prep your scheduled meals and ingredients will make tomorrow completely effortless. Check your active meal plan and set yourself up for a smooth, nourishing day ahead!', NULL, 'en'),
    ('ULTRA_EVENING_SLEEP_WIND_DOWN', 'Evening Sleep Wind-down', 'TEXT', E'Time to rest and recharge, {{First Name}}! \n To support overnight recovery and metabolic balance, let''s power down screens and wind down for the night. Wishing you deep, peaceful sleep!', NULL, 'en'),
    ('ULTRA_ON_THE_MOVE_TRAVEL_SWAP', 'On-the-Move Travel Swap', 'TEXT', 'We''ve got you covered completely, {{first_name}}! ✈️ Your coach and concierge have adjusted your meal plan based on your travel. Within 5 minutes, we have pre-screened your hotel/restaurant options. Enjoy your trip with peace of mind!', NULL, 'en'),
    ('ULTRA_CONCIERGE_HEALTH_SUMMARY', 'Concierge Health Summary', 'TEXT', 'Hello {{first_name}}! 📈 Your 3-day concierge health summary is ready. Your overnight HRV is excellent, and your body composition trend is progressing beautifully. Your coach is keeping everything optimized for you!', NULL, 'en'),
    ('ULTRA_1_1_STRATEGIC_REVIEW', '1:1 Strategic Review', 'TEXT', 'Let''s review our week, {{first_name}}! 🗓️ Let''s connect for your weekly 1:1 strategic review to audit your biomarkers and customize your logistics for the week ahead: {{calendar_link}}', NULL, 'en'),
    ('ULTRA_WEEKLY_BODY_PARAMETER_FEEDBACK', 'Weekly Body Parameter Feedback', 'TEXT', 'Wishing you a peaceful, restful weekend, {{first_name}}. 👑 Your weekly concierge body parameter report is complete. Your recovery metrics and body composition trends are moving beautifully. We have optimized next week''s logistics to perfectly match your body''s vibrant progress. You are fully cared for, and we are honored to manage your wellness journey.', NULL, 'en'),
    ('ULTRA_RENEWAL_VALUE_NUDGE', 'Renewal Value Nudge', 'TEXT', 'Hello, {{first_name}}! 🥂 We are so honored to manage your daily health logistics and auto-pilot support. Just a gentle note that your premium service is scheduled for renewal on {{renewal_date}}. No action is needed!', NULL, 'en'),
    ('ULTRA_PLAN_EXPIRY_ALERT', 'Plan Expiry Alert', 'TEXT', 'Hi {{first_name}}, quick heads-up! ⏰ Your current plan path comes to a close tomorrow. To keep your daily coach accountability, real-time swaps, and custom workouts active, you can easily renew here: {{direct_payment_link}}.', NULL, 'en'),
    ('ULTRA_ACCOUNT_HOLD_NOTICE', 'Account Hold Notice', 'TEXT', 'Hi {{first_name}}! ⏸️ Your active plan guides are on a gentle pause. Your historical scale data, logs, and meal records are stored safely. Whenever you''re ready to jump back in, we are right here to welcome you.', NULL, 'en'),
    ('ULTRA_AT_HOME_BLOOD_AUDIT', 'At-Home Blood Audit', 'TEXT', 'Biomarker Check-in, {{first_name}}! 🩸 To keep your metabolic plan perfectly aligned with your body, it is time for your pre-scheduled blood audit. Our partner lab will connect shortly to arrange sample collection.', NULL, 'en'),
    ('ULTRA_WEEKLY_SHOPPING_BASKET', 'Weekly Shopping Basket (draft from v8.1 frequency matrix)', 'TEXT', 'Happy Saturday, {{first_name}}! 🛒 Your concierge shopping basket for the week is ready. Please use it to prepare for the meals in your approved plan, and let us know if an item needs to be swapped before shopping. We will keep the kitchen plan aligned with your preferences!', NULL, 'en'),
    ('ULTRA_HOME_MAID_LUNCH_DELIVERY', 'Home Maid Lunch / Delivery (draft from v8.1 frequency matrix)', 'TEXT', 'Hello! 🍽️ Please follow today''s approved meal plan and portion guide for lunch preparation and delivery. Once lunch has been prepared and delivered, please confirm here. If an ingredient or timing issue comes up, let the concierge know so it can be coordinated.', NULL, 'en')
ON CONFLICT (template_code) DO UPDATE
SET template_name = EXCLUDED.template_name,
    message_type = EXCLUDED.message_type,
    message_content = EXCLUDED.message_content,
    language = EXCLUDED.language,
    updated_at = CURRENT_TIMESTAMP;

-- ============================================================
-- 4. MESSAGE SCHEDULES (current runtime values, insert-only)
-- A row is inserted only when no row with the same business values
-- exists. is_active in the DB is operator-managed and never reverted.
-- Every row is pinned to phase P1 until phase-wise scheduling is
-- introduced.
-- ============================================================
WITH desired (
    tier_name, phase_name, day_offset, task_type, template_code, schedule_type,
    send_time, start_time, end_time, interval_minutes, day_of_week, is_active
) AS (
    VALUES
    -- Foundation
    ('Foundation', 'P1', NULL::integer, 'WEIGHT_REMINDER', 'FOUNDATION_WAKE_UP_SCALE_READING', 'DAILY', TIME '07:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, TRUE),
    ('Foundation', 'P1', NULL::integer, 'LUNCH_GUIDE', 'FOUNDATION_NOURISHING_LUNCH_GUIDE', 'DAILY', TIME '12:30:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    ('Foundation', 'P1', NULL::integer, 'GREENS_NUDGE', 'FOUNDATION_WEEKLY_GROCERY_STOCK_UP', 'WEEKLY', TIME '10:00:00', NULL::time, NULL::time, NULL::integer, 6, TRUE),
    ('Foundation', 'P1', NULL::integer, 'PARAMETER_DIGEST', 'FOUNDATION_WEEKLY_BODY_PARAMETER_FEEDBACK', 'WEEKLY', TIME '17:00:00', NULL::time, NULL::time, NULL::integer, 6, FALSE),
    -- Pro
    ('Pro', 'P1', NULL::integer, 'WEIGHT_REMINDER', 'PRO_WAKE_UP_SCALE_READING', 'DAILY', TIME '07:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, TRUE),
    ('Pro', 'P1', NULL::integer, 'HYDRATION_REMINDER', 'PRO_HOURLY_OSMOTIC_HYDRATION_CHECK', 'HOURLY', NULL::time, TIME '08:00:00', TIME '20:00:00', 60, NULL::integer, TRUE),
    ('Pro', 'P1', NULL::integer, 'BREAKFAST_REMINDER', 'PRO_BREAKFAST_CUE_BRANCH_B', 'DAILY', TIME '08:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    ('Pro', 'P1', NULL::integer, 'LUNCH_GUIDE', 'PRO_NOURISHING_LUNCH_GUIDE', 'DAILY', TIME '13:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    ('Pro', 'P1', NULL::integer, 'PREP_NUDGE', 'PRO_NEXT_DAY_PREP_NUDGE', 'DAILY', TIME '19:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, TRUE),
    ('Pro', 'P1', NULL::integer, 'SLEEP_WIND_DOWN', 'PRO_EVENING_SLEEP_WIND_DOWN', 'DAILY', TIME '21:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, TRUE),
    -- Max
    ('Max', 'P1', NULL::integer, 'HYDRATION_REMINDER', 'MAX_HOURLY_HYDRATION_HABIT_LOOP', 'HOURLY', NULL::time, TIME '08:00:00', TIME '20:00:00', 60, NULL::integer, TRUE),
    -- Ultra
    ('Ultra', 'P1', NULL::integer, 'HYDRATION_REMINDER', 'ULTRA_HOURLY_CONCIERGE_HYDRATION_SYNC', 'HOURLY', NULL::time, TIME '08:00:00', TIME '20:00:00', 60, NULL::integer, TRUE),
    -- Pro
    ('Pro', 'P1', NULL::integer, 'PARAMETER_DIGEST', 'PRO_WEEKLY_BODY_PARAMETER_FEEDBACK', 'WEEKLY', TIME '17:00:00', NULL::time, NULL::time, NULL::integer, 6, FALSE),
    ('Pro', 'P1', NULL::integer, 'GROCERY_STOCK_UP', 'PRO_WEEKLY_GROCERY_STOCK_UP', 'WEEKLY', TIME '10:00:00', NULL::time, NULL::time, NULL::integer, 6, TRUE),
    ('Pro', 'P1', NULL::integer, 'SUPPLEMENT_REMINDER', 'PRO_CLINICAL_SUPPLEMENT_REMINDER', 'DAILY', TIME '14:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    ('Pro', 'P1', NULL::integer, 'FASTED_ACTIVITY', 'PRO_ACTIVITY_CUE_BRANCH_A', 'DAILY', TIME '07:30:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    -- Max
    ('Max', 'P1', NULL::integer, 'PARAMETER_DIGEST', 'MAX_WEEKLY_BODY_PARAMETER_FEEDBACK', 'WEEKLY', TIME '17:00:00', NULL::time, NULL::time, NULL::integer, 6, FALSE),
    ('Max', 'P1', NULL::integer, 'GROCERY_STOCK_UP', 'MAX_GROCERY_STOCK_UP', 'WEEKLY', TIME '10:00:00', NULL::time, NULL::time, NULL::integer, 6, TRUE),
    ('Max', 'P1', NULL::integer, 'HABIT_AUDIT', 'MAX_DAILY_HABIT_AUDIT_CHECK_IN', 'DAILY', TIME '21:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, TRUE),
    ('Max', 'P1', NULL::integer, 'PREP_NUDGE', 'MAX_PREP_ACTIVE_SWAP_NUDGE', 'DAILY', TIME '19:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, TRUE),
    ('Max', 'P1', NULL::integer, 'SUPPLEMENT_REMINDER', 'MAX_MICRONUTRIENT_REMINDER', 'DAILY', TIME '14:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    ('Max', 'P1', NULL::integer, 'LUNCH_GUIDE', 'MAX_NOURISHING_LUNCH_GUIDE', 'DAILY', TIME '13:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    ('Max', 'P1', NULL::integer, 'BREAKFAST_REMINDER', 'MAX_BREAKFAST_CUE_SWAPS', 'DAILY', TIME '08:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    ('Max', 'P1', NULL::integer, 'WEIGHT_REMINDER', 'MAX_WAKE_UP_SCALE_READING', 'DAILY', TIME '07:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, TRUE),
    -- Ultra
    ('Ultra', 'P1', NULL::integer, 'PARAMETER_DIGEST', 'ULTRA_WEEKLY_BODY_PARAMETER_FEEDBACK', 'WEEKLY', TIME '17:00:00', NULL::time, NULL::time, NULL::integer, 6, FALSE),
    ('Ultra', 'P1', NULL::integer, 'PREP_STRATEGY_CARD', 'ULTRA_NEXT_DAY_PREP_STRATEGY_CARD', 'DAILY', TIME '19:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    ('Ultra', 'P1', NULL::integer, 'SUPPLEMENT_REMINDER', 'ULTRA_CLINICAL_SUPPLEMENT_REMINDER', 'DAILY', TIME '14:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    ('Ultra', 'P1', NULL::integer, 'LUNCH_GUIDE', 'ULTRA_NOURISHING_LUNCH_GUIDE', 'DAILY', TIME '13:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    ('Ultra', 'P1', NULL::integer, 'WEIGHT_REMINDER', 'ULTRA_WAKE_UP_SCALE_READING', 'DAILY', TIME '07:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, TRUE),
    -- Pro
    ('Pro', 'P1', 1, 'FORTNIGHTLY_MEAL_PLAN', 'PRO_FORTNIGHTLY_METABOLIC_MEAL_PLAN_DELIVERY', 'FORTNIGHTLY', TIME '09:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    -- Max
    ('Max', 'P1', NULL::integer, 'WEEKLY_MEAL_PLAN', 'MAX_WEEKLY_CUSTOM_MEAL_PLAN_DELIVERY', 'WEEKLY', TIME '18:00:00', NULL::time, NULL::time, NULL::integer, 0, FALSE),
    ('Max', 'P1', NULL::integer, 'WORKOUT_NUDGE', 'MAX_WORKOUT_NUDGE_MUSIC', 'DAILY', TIME '07:30:00', NULL::time, NULL::time, NULL::integer, NULL::integer, TRUE),
    -- Ultra
    ('Ultra', 'P1', NULL::integer, 'MAID_LUNCH_DELIVERY', 'ULTRA_HOME_MAID_LUNCH_DELIVERY', 'DAILY', TIME '13:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    ('Ultra', 'P1', NULL::integer, 'GROCERY_STOCK_UP', 'ULTRA_WEEKLY_SHOPPING_BASKET', 'WEEKLY', TIME '10:00:00', NULL::time, NULL::time, NULL::integer, 6, TRUE),
    ('Ultra', 'P1', NULL::integer, 'SLEEP_WIND_DOWN', 'ULTRA_EVENING_SLEEP_WIND_DOWN', 'DAILY', TIME '21:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, TRUE),
    ('Ultra', 'P1', NULL::integer, 'WEEKLY_MEAL_PLAN', 'ULTRA_WEEKLY_EXECUTIVE_CONCIERGE_MEAL_PLAN_DELIVERY', 'WEEKLY', TIME '18:00:00', NULL::time, NULL::time, NULL::integer, 0, FALSE),
    ('Ultra', 'P1', NULL::integer, 'MAID_PREP_VERIFICATION', 'ULTRA_MAID_PREP_VERIFICATION', 'DAILY', TIME '08:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE),
    ('Ultra', 'P1', NULL::integer, 'MAID_PREP_CARD', 'ULTRA_MAID_PREP_CARD_DELIVERY', 'DAILY', TIME '19:00:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE)
)
INSERT INTO message_schedules (
    tier_id, phase_id, day_offset, task_type, template_id, schedule_type,
    send_time, start_time, end_time, interval_minutes, day_of_week, is_active
)
SELECT
    t.tier_id,
    p.phase_id,
    d.day_offset,
    d.task_type,
    tp.template_id,
    d.schedule_type,
    d.send_time,
    d.start_time,
    d.end_time,
    d.interval_minutes,
    d.day_of_week,
    d.is_active
FROM desired d
JOIN tiers t ON t.tier_name = d.tier_name
JOIN templates tp ON tp.template_code = d.template_code
LEFT JOIN phases p ON p.phase_name = d.phase_name
WHERE NOT EXISTS (
    SELECT 1
    FROM message_schedules ms
    JOIN tiers t2 ON t2.tier_id = ms.tier_id
    JOIN templates tp2 ON tp2.template_id = ms.template_id
    LEFT JOIN phases p2 ON p2.phase_id = ms.phase_id
    WHERE t2.tier_name = d.tier_name
      AND p2.phase_name IS NOT DISTINCT FROM d.phase_name
      AND ms.day_offset IS NOT DISTINCT FROM d.day_offset
      AND ms.task_type = d.task_type
      AND tp2.template_code = d.template_code
      AND ms.schedule_type = d.schedule_type
      AND ms.send_time IS NOT DISTINCT FROM d.send_time
      AND ms.start_time IS NOT DISTINCT FROM d.start_time
      AND ms.end_time IS NOT DISTINCT FROM d.end_time
      AND ms.interval_minutes IS NOT DISTINCT FROM d.interval_minutes
      AND ms.day_of_week IS NOT DISTINCT FROM d.day_of_week
);

-- ============================================================
-- 5. TEST MEMBERS (test profiles, not real customer records)
-- phone_number powers the scheduler's @mention footer; members
-- without a number get no footer.
-- ============================================================
INSERT INTO members (
    member_code, member_name, phone_number, whatsapp_sender_id, joining_date, tier_id, phase_id
)
SELECT
    v.member_code, v.member_name, v.phone_number, v.whatsapp_sender_id,
    v.joining_date, t.tier_id, p.phase_id
FROM (VALUES
    ('TEST_FAIZAN', 'Faizan', '919674671233', NULL::varchar, DATE '2026-10-06', 'Pro', 'P1'),
    ('TEST_ZYVE_USER', 'Zyve Test User', NULL::varchar, NULL::varchar, DATE '2026-09-26', 'Max', 'P1'),
    ('TEST_AHAD', 'Ahad', '918948937671', NULL::varchar, DATE '2026-10-09', 'Ultra', 'P1')
) AS v(member_code, member_name, phone_number, whatsapp_sender_id, joining_date, tier_name, phase_name)
JOIN tiers t ON t.tier_name = v.tier_name
LEFT JOIN phases p ON p.phase_name = v.phase_name
WHERE NOT EXISTS (SELECT 1 FROM members m WHERE m.member_code = v.member_code);

-- ============================================================
-- 6. TEST CHAT ROUTES
-- '9189...' / '9196...' individual chats are placeholders and are
-- deliberately not linked to any member below.
-- ============================================================
INSERT INTO whatsapp_groups (periskope_chat_id, group_name)
VALUES
    ('120363412042215031@g.us', 'Dev Test Group 01'),
    ('120363431222993492@g.us', 'Multi Membership holder test'),
    ('919674671233@c.us', 'Faizan Individual Chat - PLACEHOLDER NOT LINKED'),
    ('918948937671@c.us', 'Ahad Individual Chat - PLACEHOLDER NOT LINKED')
ON CONFLICT (periskope_chat_id) DO NOTHING;

-- ============================================================
-- 7. TEST GROUP MEMBERSHIPS
-- ============================================================
INSERT INTO group_members (group_id, member_id)
SELECT wg.group_id, m.member_id
FROM whatsapp_groups wg
JOIN members m ON m.member_code = 'TEST_AHAD'
WHERE wg.periskope_chat_id = '120363412042215031@g.us'
  AND NOT EXISTS (
      SELECT 1
      FROM group_members existing
      WHERE existing.group_id = wg.group_id
        AND existing.member_id = m.member_id
  );
INSERT INTO group_members (group_id, member_id)
SELECT wg.group_id, m.member_id
FROM whatsapp_groups wg
JOIN members m ON m.member_code = 'TEST_FAIZAN'
WHERE wg.periskope_chat_id = '120363412042215031@g.us'
  AND NOT EXISTS (
      SELECT 1
      FROM group_members existing
      WHERE existing.group_id = wg.group_id
        AND existing.member_id = m.member_id
  );
INSERT INTO group_members (group_id, member_id)
SELECT wg.group_id, m.member_id
FROM whatsapp_groups wg
JOIN members m ON m.member_code = 'TEST_FAIZAN'
WHERE wg.periskope_chat_id = '120363431222993492@g.us'
  AND NOT EXISTS (
      SELECT 1
      FROM group_members existing
      WHERE existing.group_id = wg.group_id
        AND existing.member_id = m.member_id
  );
INSERT INTO group_members (group_id, member_id)
SELECT wg.group_id, m.member_id
FROM whatsapp_groups wg
JOIN members m ON m.member_code = 'TEST_ZYVE_USER'
WHERE wg.periskope_chat_id = '120363412042215031@g.us'
  AND NOT EXISTS (
      SELECT 1
      FROM group_members existing
      WHERE existing.group_id = wg.group_id
        AND existing.member_id = m.member_id
  );
INSERT INTO group_members (group_id, member_id)
SELECT wg.group_id, m.member_id
FROM whatsapp_groups wg
JOIN members m ON m.member_code = 'TEST_ZYVE_USER'
WHERE wg.periskope_chat_id = '120363431222993492@g.us'
  AND NOT EXISTS (
      SELECT 1
      FROM group_members existing
      WHERE existing.group_id = wg.group_id
        AND existing.member_id = m.member_id
  );

COMMIT;

-- ============================================================
-- VERIFICATION
-- ============================================================
SELECT tier_id, tier_name FROM tiers ORDER BY tier_id;

SELECT phase_id, phase_name, phase_number, start_day, end_day
FROM phases ORDER BY phase_number;

SELECT
    t.tier_name,
    ms.schedule_id,
    ms.task_type,
    ms.schedule_type,
    ms.send_time,
    ms.start_time,
    ms.end_time,
    ms.interval_minutes,
    ms.day_of_week,
    ms.is_active,
    tp.template_code
FROM message_schedules ms
JOIN tiers t ON t.tier_id = ms.tier_id
JOIN templates tp ON tp.template_id = ms.template_id
ORDER BY t.tier_id, ms.schedule_id;

SELECT
    m.member_code,
    m.member_name,
    t.tier_name,
    p.phase_name,
    m.is_active
FROM members m
LEFT JOIN tiers t ON t.tier_id = m.tier_id
LEFT JOIN phases p ON p.phase_id = m.phase_id
ORDER BY m.member_code;

BEGIN;

ALTER TABLE public.phases
    ALTER COLUMN start_day DROP NOT NULL,
    ALTER COLUMN end_day DROP NOT NULL;

UPDATE public.phases
SET start_day = NULL,
    end_day = NULL;

COMMIT;
