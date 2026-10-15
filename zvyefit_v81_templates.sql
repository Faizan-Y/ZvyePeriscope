-- ============================================================
-- ZYVEFIT v8.1: FINAL TEMPLATE CATALOG + SCHEDULABLE SCHEDULES
-- Source: Zyvefit_WA_Communication_Flow_v8.1.xlsx
--
-- What this script does:
--   1. Upserts all 65 workbook blueprint templates (preserves media_url).
--   2. Updates matching recurring schedule rows to use tier-specific templates/times.
--   3. Inserts missing recurring schedule rows supported by the frozen schema.
--   4. Stages all targeted schedules as INACTIVE; no live sends are enabled.
--
-- IMPORTANT:
--   * Stop scheduler.py before applying this script.
--   * Do not activate schedules until dry-run previews and routing are verified.
--   * Three document schedules wait for an approved template media_url.
--   * Max workout and Ultra sleep schedules wait until their link placeholders are
--     replaced with actual links in templates.message_content.
--   * Foundation monthly meal roadmap remains a template only: no MONTHLY recurrence
--     type/plan-cycle anchor exists in the approved schema.
--   * ON-DEMAND/instant, EVERY 3 DAYS, billing/expiry, coach appointments, lab audits,
--     and Ultra Family/Wife Chat workflows remain template-only pending trigger/routing
--     support. Family-chat rows are not scheduled because current routing cannot
--     distinguish the intended audience from other linked groups.
--   * No permanent tables or columns are created or altered.
-- ============================================================

BEGIN;

DO $preflight$
DECLARE
    tier_count INTEGER;
BEGIN
    SELECT COUNT(DISTINCT tier_name)
      INTO tier_count
      FROM tiers
     WHERE tier_name IN ('Foundation', 'Pro', 'Max', 'Ultra');

    IF tier_count <> 4 THEN
        RAISE EXCEPTION
          'Expected the four approved tiers (Foundation, Pro, Max, Ultra) before seeding. Found %.',
          tier_count;
    END IF;
END;
$preflight$;

-- ------------------------------------------------------------
-- 1. Upsert the full source template catalog (65 rows).
-- `media_url` is omitted from INSERT and UPDATE so an approved URL is preserved.
-- Source row First Name placeholders are normalized to {first_name}, which the
-- current scheduler renderer supports. Other event/link placeholders are kept as
-- explicit snake_case placeholders and are not scheduled until resolved.
-- HTML <br> in the Ultra maid card becomes a plain line break.
-- ------------------------------------------------------------
INSERT INTO templates (
    template_code, template_name, message_type, message_content, language
)
VALUES
    (E'FOUNDATION_WAKE_UP_SCALE_READING', E'Wake-up & Scale Reading', E'TEXT', E'Good morning, {{first_name}}! 🌅 Sending you a warm, gentle start to your day. Let''s take a loving check-in with your body—whenever you are ready, please share a quick photo of your scale''s screen right here. We are right here with you!', E'en'),
    (E'FOUNDATION_MONTHLY_MEAL_PLAN_ROADMAP_DELIVERY', E'Monthly Meal Plan Roadmap Delivery', E'DOCUMENT', E'Here is your monthly nourishing meal roadmap, {{first_name}}! 🍲 Designed to give you clear, gentle structure for the month ahead while honoring your personal lifestyle pace. Whenever you''re ready, dive in and let this fuel your wellbeing!', E'en'),
    (E'FOUNDATION_NOURISHING_LUNCH_GUIDE', E'Nourishing Lunch Guide', E'TEXT', E'Here is your nourishing lunch recommendation, {{first_name}}! 🍲 Balanced gently to keep your energy steady today. Enjoy your meal!', E'en'),
    (E'FOUNDATION_WEEKLY_GROCERY_STOCK_UP', E'Weekly Grocery Stock-up', E'TEXT', E'Happy Saturday, {{first_name}}! 🛒 If you are planning a market trip today, here are some fresh, nourishing greens we recommend stocking up on: spinach, cucumber, bell peppers, and zucchini. Let us know if you need any other ideas!', E'en'),
    (E'FOUNDATION_WEEKLY_BODY_PARAMETER_FEEDBACK', E'Weekly Body Parameter Feedback', E'TEXT', E'Hi {{first_name}}! 🌸 As we wrap up the week, let''s take a warm moment to appreciate your body''s journey. Your scale trends show gentle, beautiful progress in your body parameters. We are so incredibly proud of your consistency. Thank you for trusting us with your health—it is 100% our passion to support you!', E'en'),
    (E'FOUNDATION_RENEWAL_VALUE_NUDGE', E'Renewal Value Nudge', E'TEXT', E'Hello, {{first_name}}! 🌟 We are so honored to support your health. Just a gentle, caring note that your auto-renewal is coming up on {{renewal_date}}. We are so excited to keep walking this path of wellness with you!', E'en'),
    (E'FOUNDATION_PLAN_EXPIRY_ALERT', E'Plan Expiry Alert', E'TEXT', E'Hi {{first_name}}, just a gentle, warm heads-up! ⏰ Your current plan path comes to a close tomorrow. To keep your daily meal guides flowing smoothly, you can easily renew here: {{direct_payment_link}}.', E'en'),
    (E'FOUNDATION_ACCOUNT_HOLD_NOTICE', E'Account Hold Notice', E'TEXT', E'Hi {{first_name}}! ⏸️ Your active plan guides are on a gentle, restful pause. Your historical scale data, logs, and meal records are stored safely in our hearts and system. Whenever you''re ready to jump back in, we are right here to welcome you with open arms.', E'en'),
    (E'PRO_WAKE_UP_SCALE_READING', E'Wake-up & Scale Reading', E'TEXT', E'Good morning, {{first_name}}! 🌅 Sending you a warm, gentle start to your day. Let''s take a loving check-in with your body—whenever you are ready, please share a quick photo of your scale''s screen right here. We are right here with you!', E'en'),
    (E'PRO_ACTIVITY_CUE_BRANCH_A', E'Activity Cue (Branch A)', E'TEXT', E'Good morning, {{first_name}}! ⚡ Time for your planned morning movement. Please listen to your body and execute your session in a way that feels rewarding. Whenever you''re finished, let us know so we can send your breakfast guide!', E'en'),
    (E'PRO_BREAKFAST_CUE_BRANCH_B', E'Breakfast Cue (Branch B)', E'TEXT', E'Time to nourish your beautiful cells, {{first_name}}! 🍳 Here is your precise fuel: **3 Egg whites, 40g Oats, and 1/2 avocado**. Enjoy every bite—your body will thank you for this structural balance and love!', E'en'),
    (E'PRO_HOURLY_OSMOTIC_HYDRATION_CHECK', E'Hourly Osmotic Hydration Check', E'TEXT', E'Hourly Osmotic Hydration Check, {{first_name}}! 💧 Time for your hourly glass (~250ml) to keep your cellular enzymes active and mental focus sharp. Sip and thrive!', E'en'),
    (E'PRO_FORTNIGHTLY_METABOLIC_MEAL_PLAN_DELIVERY', E'Fortnightly Metabolic Meal Plan Delivery', E'DOCUMENT', E'Your bi-weekly metabolic meal plan is ready, {{first_name}}! 🥗 Tailored with precision to keep your glycemic balance steady and your cellular energy high over the next 14 days. Let''s fuel your progress!', E'en'),
    (E'PRO_MEAL_PLAN_REFINEMENT_ACKNOWLEDGEMENT', E'Meal Plan Refinement Acknowledgement', E'TEXT', E'Got it, {{first_name}}! 💬 We''ve received your meal plan adjustment request. Our coaching team is already recalibrating your macros and metabolic targets to match your needs. We''ll send your updated plan right over shortly!', E'en'),
    (E'PRO_REFINED_MEAL_PLAN_DELIVERY', E'Refined Meal Plan Delivery', E'DOCUMENT', E'Here is your refined metabolic meal plan, {{first_name}}! 🎯 Updated with your requested adjustments while keeping your precision macro balance intact. Let''s keep your momentum going strong!', E'en'),
    (E'PRO_NOURISHING_LUNCH_GUIDE', E'Nourishing Lunch Guide', E'TEXT', E'Time to refuel, {{first_name}}! 🥗 Your precise metabolic lunch is ready: **150g Grilled Chicken + 100g Jasmine Rice + 80g Asparagus**. Let this structural balance fuel your afternoon with steady focus and care!', E'en'),
    (E'PRO_CLINICAL_SUPPLEMENT_REMINDER', E'Clinical Supplement Reminder', E'TEXT', E'A quick supplement reminder, {{first_name}}! 💊 Let''s support your thyroid and lipid profiles today: **1x Omega-3 + 1x Vitamin D3+K2**. Take a loving moment for yourself!', E'en'),
    (E'PRO_NEXT_DAY_PREP_NUDGE', E'Next-Day Prep Nudge', E'TEXT', E'Nurturing tomorrow, {{first_name}}! 🔪 Prepping tonight makes tomorrow effortless and peaceful: **🥩 150g raw chicken/paneer, 🥦 100g broccoli & 50g carrots, 🍚 80g raw rice**. Set yourself up for absolute peace of mind tomorrow!', E'en'),
    (E'PRO_EVENING_SLEEP_WIND_DOWN', E'Evening Sleep Wind-down', E'TEXT', E'Time to rest, {{first_name}}. 💤 To support your body''s overnight healing and morning fasting glucose, let''s gently power down screens in 15 minutes. Wishing you peaceful dreams!', E'en'),
    (E'PRO_WEEKLY_GROCERY_STOCK_UP', E'Weekly Grocery Stock-up', E'TEXT', E'Bio-Fuel Prep Nudge, {{first_name}}! 🥦 To ensure your body has everything it needs for metabolic optimization next week, here is your precision grocery basket: **500g Asparagus, 1kg Spinach, 400g Broccoli, 500g Bell Peppers, 300g Cucumber**.', E'en'),
    (E'PRO_WEEKLY_BODY_PARAMETER_FEEDBACK', E'Weekly Body Parameter Feedback', E'TEXT', E'Hello {{first_name}}! 🌸 Your end-of-week body parameter feedback is ready. Your clinical data shows steady metabolic alignment and lovely composition trends. Your dedication is inspiring, and we are honored to protect your health with precision!', E'en'),
    (E'PRO_COACH_AUDIT_UPDATES', E'Coach Audit & Updates', E'TEXT', E'Hi {{first_name}}! 📈 Your 3-day metabolic update is ready. Your weight trend shows lovely glycemic stability, and water compliance hit 88%. Your coach has refined your targets to keep you thriving!', E'en'),
    (E'PRO_1_1_COACHING_CHECK_IN', E'1:1 Coaching Check-in', E'TEXT', E'Let''s connect, {{first_name}}! 🔬 It''s time for our fortnightly deep dive. Let''s schedule a 1:1 voice or video chat to celebrate your progress and adjust your plans: {{calendar_link}}', E'en'),
    (E'PRO_RENEWAL_VALUE_NUDGE', E'Renewal Value Nudge', E'TEXT', E'Hello, {{first_name}}! 🌟 We are so honored to support your health. Just a gentle note that your auto-renewal is coming up on {{renewal_date}}. We are excited to keep walking this path with you!', E'en'),
    (E'PRO_PLAN_EXPIRY_ALERT', E'Plan Expiry Alert', E'TEXT', E'Hi {{first_name}}, quick heads-up! ⏰ Your current plan path comes to a close tomorrow. To prevent your twice-weekly data reviews and custom meal guides from pausing, you can easily renew here: {{direct_payment_link}}.', E'en'),
    (E'PRO_ACCOUNT_HOLD_NOTICE', E'Account Hold Notice', E'TEXT', E'Hi {{first_name}}! ⏸️ Your active plan guides are on a gentle pause. Your historical scale data, logs, and meal records are stored safely. Whenever you''re ready to jump back in, we are right here to welcome you.', E'en'),
    (E'PRO_BLOOD_AUDIT_COLLECTION', E'Blood Audit Collection', E'TEXT', E'Biomarker Check-in, {{first_name}}! 🩸 To keep your metabolic plan perfectly aligned with your body, it is time for your pre-scheduled blood audit. Our partner lab will connect shortly to arrange sample collection.', E'en'),
    (E'MAX_WAKE_UP_SCALE_READING', E'Wake-up & Scale Reading', E'TEXT', E'Good morning, {{first_name}}! 🌅 Sending you a warm, gentle start to your day. Let''s take a loving check-in with your body—whenever you are ready, please share a quick photo of your scale''s screen right here. We are right here with you!', E'en'),
    (E'MAX_WORKOUT_NUDGE_MUSIC', E'Workout Nudge & Music', E'TEXT', E'Good morning, {{first_name}}! 🏋️ Let''s wake up with some joyful movement. To help you get in the zone, here is your high-energy playlist: {{spotify_max_link}} / {{apple_max_link}}. Let us know when you''re done to unlock breakfast!', E'en'),
    (E'MAX_BREAKFAST_CUE_SWAPS', E'Breakfast Cue (Swaps)', E'TEXT', E'Time to nourish, {{first_name}}! ☀️ Here is your custom breakfast: **3 Egg whites, 1 slice sourdough, 1/2 avocado**. If you''re on the move or need a gentle swap, just let us know—we''ve got options!', E'en'),
    (E'MAX_HOURLY_HYDRATION_HABIT_LOOP', E'Hourly Hydration Habit Loop', E'TEXT', E'Hourly Sip Check-in, {{first_name}}! 🥤 A gentle splash of water this hour keeps your mind clear and your habit streak rolling. Keep your water bottle close!', E'en'),
    (E'MAX_WEEKLY_CUSTOM_MEAL_PLAN_DELIVERY', E'Weekly Custom Meal Plan Delivery', E'DOCUMENT', E'Your custom weekly meal plan for the week ahead is here, {{first_name}}! 🥑 Carefully structured with your favorite active swaps and preferences. Check it out, and remember—we can always adjust together if your week shifts!', E'en'),
    (E'MAX_MEAL_PLAN_REFINEMENT_ACKNOWLEDGEMENT', E'Meal Plan Refinement Acknowledgement', E'TEXT', E'No stress at all, {{first_name}}! 🌿 We love adjusting with you. Your change request is logged, and we''re modifying your swaps to make sure your meals fit your week effortlessly. Hang tight—your fresh plan is on its way!', E'en'),
    (E'MAX_REFINED_MEAL_PLAN_DELIVERY', E'Refined Meal Plan Delivery', E'DOCUMENT', E'Your updated weekly meal plan is ready, {{first_name}}! ✨ Tailored around your fresh preferences so healthy eating feels completely peaceful and flexible. Take a look and let us know how it feels!', E'en'),
    (E'MAX_NOURISHING_LUNCH_GUIDE', E'Nourishing Lunch Guide', E'TEXT', E'Nourishing lunch time, {{first_name}}! 🍽️ Here is your planned meal: **150g Grilled Chicken + 100g Jasmine Rice + Veggies**. If you don''t have this or need a warm swap, let us know—we can adjust together!', E'en'),
    (E'MAX_MICRONUTRIENT_REMINDER', E'Micronutrient Reminder', E'TEXT', E'A friendly supplement check-in, {{first_name}}! 💊 Let''s keep your energy high and body strong: **1x Multivitamin + 1x Magnesium**. Take a quick moment for yourself!', E'en'),
    (E'MAX_PREP_ACTIVE_SWAP_NUDGE', E'Prep & Active Swap Nudge', E'TEXT', E'Set up for a peaceful tomorrow, {{first_name}}! 🥗 Spend 10 minutes tonight prepping: **150g Salmon + 120g Sweet Potato**. Missing something? No stress—just tell us what''s in your fridge and we''ll swap it!', E'en'),
    (E'MAX_DAILY_HABIT_AUDIT_CHECK_IN', E'Daily Habit Audit Check-in', E'TEXT', E'Sweet dreams, {{first_name}}! 🧘 Let''s close out our day with a gentle, non-judgmental check-in. How did today feel with your food and movement? We love celebrating every win, big or small!', E'en'),
    (E'MAX_GROCERY_STOCK_UP', E'Grocery Stock-up', E'TEXT', E'Weekly Kitchen Prep, {{first_name}}! 🥬 Let''s build your consistency safety net. Stocking your vegetables on Saturday means you have zero excuses during a busy week. Here is your customized vegetable shopping list: **600g Broccoli, 500g Zucchini, 400g Mushrooms, 1kg Spinach, 500g Tomatoes**.', E'en'),
    (E'MAX_WEEKLY_BODY_PARAMETER_FEEDBACK', E'Weekly Body Parameter Feedback', E'TEXT', E'Happy Saturday, {{first_name}}! ✨ Your weekly body parameter review is ready. Your consistency score is amazing, and your body composition is aligning beautifully with your habit loops. You are doing fantastic, and we love celebrating every step of your progress!', E'en'),
    (E'MAX_COACH_AUDIT_UPDATES', E'Coach Audit & Updates', E'TEXT', E'Hi {{first_name}}! 📈 Your 3-day log review is ready. Your consistency is amazing, and we love seeing your habit streak grow. Your coach has updated your targets to fit your busy week!', E'en'),
    (E'MAX_1_1_COACHING_VOICE_SESSION', E'1:1 Coaching Voice Session', E'TEXT', E'Time for our weekly check-in, {{first_name}}! 🗓️ Let''s look at your habit loops, scale patterns, and make sure your program flows beautifully with your busy life. Book your call here: {{calendar_link}}', E'en'),
    (E'MAX_RENEWAL_VALUE_NUDGE', E'Renewal Value Nudge', E'TEXT', E'Hello, {{first_name}}! 🌟 We are so honored to support your health. Just a gentle note that your auto-renewal is coming up on {{renewal_date}}. We are excited to keep walking this path with you!', E'en'),
    (E'MAX_PLAN_EXPIRY_ALERT', E'Plan Expiry Alert', E'TEXT', E'Hi {{first_name}}, quick heads-up! ⏰ Your current plan path comes to a close tomorrow. To keep your daily coach accountability, real-time swaps, and custom workouts active, you can easily renew here: {{direct_payment_link}}.', E'en'),
    (E'MAX_ACCOUNT_HOLD_NOTICE', E'Account Hold Notice', E'TEXT', E'Hi {{first_name}}! ⏸️ Your active plan guides are on a gentle pause. Your historical scale data, logs, and meal records are stored safely. Whenever you''re ready to jump back in, we are right here to welcome you.', E'en'),
    (E'MAX_BLOOD_AUDIT_COLLECTION', E'Blood Audit Collection', E'TEXT', E'Biomarker Check-in, {{first_name}}! 🩸 To keep your metabolic plan perfectly aligned with your body, it is time for your pre-scheduled blood audit. Our partner lab will connect shortly to arrange sample collection.', E'en'),
    (E'ULTRA_WAKE_UP_SCALE_READING', E'Wake-up & Scale Reading', E'TEXT', E'Good morning, {{first_name}}! 🌅 Sending you a warm, gentle start to your day. Let''s take a loving check-in with your body—whenever you are ready, please share a quick photo of your scale''s screen right here. We are right here with you!', E'en'),
    (E'ULTRA_MAID_PREP_CARD_DELIVERY', E'Maid Prep Card Delivery', E'DOCUMENT', E'Good evening, {{first_name}} / {{spouse_name}}! 🥂 To make tomorrow completely seamless and restful for {{first_name}}, here is their preparation card for tomorrow''s meals. Please forward this to your maid or cook:\n*Akka, Anna, neenga kezale koduthulla breakfast matrum lunch ai prepare seiyya mudiyumaa?*\n🍳 **Breakfast (08:30 AM):** *3 Egg whites + 1 whole egg omelette, 1 slice toasted brown bread, 1/2 avocado.*\n🍽️ **Lunch (01:30 PM):** *150g chicken breast / paneer (dry/spray coconut oil), 100g cooked brown rice, one bowl boiled carrots/beans.*', E'en'),
    (E'ULTRA_MAID_PREP_VERIFICATION', E'Maid Prep Verification', E'TEXT', E'A gentle morning greeting, {{first_name}} / {{spouse_name}}! ☀️ Just a quick check-in to make sure the morning breakfast and lunch preps are rolling smoothly for {{first_name}}. Let your concierge know if you need any adjustments!', E'en'),
    (E'ULTRA_HOURLY_CONCIERGE_HYDRATION_SYNC', E'Hourly Concierge Hydration Sync', E'TEXT', E'Hourly Concierge Hydration Sync, {{first_name}}! 👑 Your hourly mineral-enhanced hydration check. Take a refreshing sip from your desk flask to maintain peak cellular vitality and executive focus!', E'en'),
    (E'ULTRA_WEEKLY_EXECUTIVE_CONCIERGE_MEAL_PLAN_DELIVERY', E'Weekly Executive Concierge Meal Plan Delivery', E'DOCUMENT', E'Your executive weekly culinary roadmap is ready, {{first_name}}! 👑 Fully synchronized with your wearable metrics and pre-sent to your home chef. Relax knowing your biological support and gourmet preferences are completely taken care of!', E'en'),
    (E'ULTRA_MEAL_PLAN_REFINEMENT_ACKNOWLEDGEMENT', E'Meal Plan Refinement Acknowledgement', E'TEXT', E'Consider it done, {{first_name}}! 👑 Your concierge team has accepted your meal plan adjustment request. We are updating your custom menu and notifying your kitchen chef right now. We''ll deliver your refined plan in just a few minutes!', E'en'),
    (E'ULTRA_REFINED_MEAL_PLAN_DELIVERY', E'Refined Meal Plan Delivery', E'DOCUMENT', E'Your refined executive meal plan is complete, {{first_name}}! 🥂 Your new selections are seamlessly updated, and your preparation cards have been auto-synced with your home kitchen. Enjoy your tailored dining with total peace of mind!', E'en'),
    (E'ULTRA_NOURISHING_LUNCH_GUIDE', E'Nourishing Lunch Guide', E'TEXT', E'Your home-cooked metabolic lunch is ready, {{first_name}}! 🥗 Balanced perfectly to keep you focused and energized all afternoon. Enjoy your peaceful, restful lunch break!', E'en'),
    (E'ULTRA_CLINICAL_SUPPLEMENT_REMINDER', E'Clinical Supplement Reminder', E'TEXT', E'A gentle protocol reminder, {{first_name}}! 👑 Let''s execute your mid-day biological support: **1x CoQ10 + 1x Thyroid Support** pre-sorted in Tray B of your kit. We hope you''re having an amazing day!', E'en'),
    (E'ULTRA_NEXT_DAY_PREP_STRATEGY_CARD', E'Next-Day Prep & Strategy Card', E'TEXT', E'Good evening, {{first_name}}! 🥂 Let''s set up tomorrow for absolute ease. Your scheduled menu is **200g Tiger Prawns + 100g Wild Rice**. We''ve already sent your preparation card to your kitchen chef. Let us know if your plans have changed or if you need any adjustments!', E'en'),
    (E'ULTRA_EVENING_SLEEP_WIND_DOWN', E'Evening Sleep Wind-down', E'TEXT', E'Wishing you a restful night, {{first_name}}. 👑 Your sleep optimization pack (**Magnesium L-Threonate + Apigenin**) is ready in Tray C. Take a moment to unwind with your custom 3-minute neural wind-down track: {{neural_audio_link}}. Sleep deeply!', E'en'),
    (E'ULTRA_ON_THE_MOVE_TRAVEL_SWAP', E'On-the-Move Travel Swap', E'TEXT', E'We''ve got you covered completely, {{first_name}}! ✈️ Your coach and concierge have adjusted your meal plan based on your travel. Within 5 minutes, we have pre-screened your hotel/restaurant options. Enjoy your trip with peace of mind!', E'en'),
    (E'ULTRA_CONCIERGE_HEALTH_SUMMARY', E'Concierge Health Summary', E'TEXT', E'Hello {{first_name}}! 📈 Your 3-day concierge health summary is ready. Your overnight HRV is excellent, and your body composition trend is progressing beautifully. Your coach is keeping everything optimized for you!', E'en'),
    (E'ULTRA_1_1_STRATEGIC_REVIEW', E'1:1 Strategic Review', E'TEXT', E'Let''s review our week, {{first_name}}! 🗓️ Let''s connect for your weekly 1:1 strategic review to audit your biomarkers and customize your logistics for the week ahead: {{calendar_link}}', E'en'),
    (E'ULTRA_WEEKLY_BODY_PARAMETER_FEEDBACK', E'Weekly Body Parameter Feedback', E'TEXT', E'Wishing you a peaceful, restful weekend, {{first_name}}. 👑 Your weekly concierge body parameter report is complete. Your recovery metrics and body composition trends are moving beautifully. We have optimized next week''s logistics to perfectly match your body''s vibrant progress. You are fully cared for, and we are honored to manage your wellness journey.', E'en'),
    (E'ULTRA_RENEWAL_VALUE_NUDGE', E'Renewal Value Nudge', E'TEXT', E'Hello, {{first_name}}! 🥂 We are so honored to manage your daily health logistics and auto-pilot support. Just a gentle note that your premium service is scheduled for renewal on {{renewal_date}}. No action is needed!', E'en'),
    (E'ULTRA_PLAN_EXPIRY_ALERT', E'Plan Expiry Alert', E'TEXT', E'Hi {{first_name}}, quick heads-up! ⏰ Your current plan path comes to a close tomorrow. To keep your daily coach accountability, real-time swaps, and custom workouts active, you can easily renew here: {{direct_payment_link}}.', E'en'),
    (E'ULTRA_ACCOUNT_HOLD_NOTICE', E'Account Hold Notice', E'TEXT', E'Hi {{first_name}}! ⏸️ Your active plan guides are on a gentle pause. Your historical scale data, logs, and meal records are stored safely. Whenever you''re ready to jump back in, we are right here to welcome you.', E'en'),
    (E'ULTRA_AT_HOME_BLOOD_AUDIT', E'At-Home Blood Audit', E'TEXT', E'Biomarker Check-in, {{first_name}}! 🩸 To keep your metabolic plan perfectly aligned with your body, it is time for your pre-scheduled blood audit. Our partner lab will connect shortly to arrange sample collection.', E'en')
ON CONFLICT (template_code) DO UPDATE
SET template_name = EXCLUDED.template_name,
    message_type = EXCLUDED.message_type,
    message_content = CASE
        -- Preserve approved links supplied for these two templates on reruns.
        WHEN templates.template_code = 'MAX_WORKOUT_NUDGE_MUSIC'
             AND POSITION('{{spotify_max_link}}' IN templates.message_content) = 0
             AND POSITION('{{apple_max_link}}' IN templates.message_content) = 0
          THEN templates.message_content
        WHEN templates.template_code = 'ULTRA_EVENING_SLEEP_WIND_DOWN'
             AND POSITION('{{neural_audio_link}}' IN templates.message_content) = 0
          THEN templates.message_content
        ELSE EXCLUDED.message_content
    END,
    language = EXCLUDED.language,
    updated_at = CURRENT_TIMESTAMP;

-- ------------------------------------------------------------
-- 2. Canonical recurring schedules representable by this schema.
-- PostgreSQL day_of_week: Sunday=0, Saturday=6.
-- Every targeted row is staged inactive for review.
-- requires_media: DOCUMENT needs its approved media_url.
-- requires_resolved_vars: schedule waits until the named URLs are in the text.
-- ------------------------------------------------------------
WITH desired(
    tier_name, task_type, schedule_type, template_code, day_offset,
    send_time, start_time, end_time, interval_minutes, day_of_week,
    requires_media, requires_resolved_vars
) AS (
    VALUES
    (E'Foundation', E'WEIGHT_REMINDER', E'DAILY', E'FOUNDATION_WAKE_UP_SCALE_READING', NULL::integer, TIME '07:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Foundation', E'LUNCH_GUIDE', E'DAILY', E'FOUNDATION_NOURISHING_LUNCH_GUIDE', NULL::integer, TIME '12:30', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Foundation', E'GREENS_NUDGE', E'WEEKLY', E'FOUNDATION_WEEKLY_GROCERY_STOCK_UP', NULL::integer, TIME '10:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Foundation', E'PARAMETER_DIGEST', E'WEEKLY', E'FOUNDATION_WEEKLY_BODY_PARAMETER_FEEDBACK', NULL::integer, TIME '17:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Pro', E'WEIGHT_REMINDER', E'DAILY', E'PRO_WAKE_UP_SCALE_READING', NULL::integer, TIME '07:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'FASTED_ACTIVITY', E'DAILY', E'PRO_ACTIVITY_CUE_BRANCH_A', NULL::integer, TIME '07:30', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'BREAKFAST_REMINDER', E'DAILY', E'PRO_BREAKFAST_CUE_BRANCH_B', NULL::integer, TIME '08:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'HYDRATION_REMINDER', E'HOURLY', E'PRO_HOURLY_OSMOTIC_HYDRATION_CHECK', NULL::integer, NULL::time, TIME '08:00', TIME '20:00', 60, NULL::integer, FALSE, FALSE),
    (E'Pro', E'FORTNIGHTLY_MEAL_PLAN', E'FORTNIGHTLY', E'PRO_FORTNIGHTLY_METABOLIC_MEAL_PLAN_DELIVERY', 1, TIME '09:00', NULL::time, NULL::time, NULL::integer, NULL::integer, TRUE, FALSE),
    (E'Pro', E'LUNCH_GUIDE', E'DAILY', E'PRO_NOURISHING_LUNCH_GUIDE', NULL::integer, TIME '13:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'SUPPLEMENT_REMINDER', E'DAILY', E'PRO_CLINICAL_SUPPLEMENT_REMINDER', NULL::integer, TIME '14:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'PREP_NUDGE', E'DAILY', E'PRO_NEXT_DAY_PREP_NUDGE', NULL::integer, TIME '19:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'SLEEP_WIND_DOWN', E'DAILY', E'PRO_EVENING_SLEEP_WIND_DOWN', NULL::integer, TIME '22:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'GROCERY_STOCK_UP', E'WEEKLY', E'PRO_WEEKLY_GROCERY_STOCK_UP', NULL::integer, TIME '10:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Pro', E'PARAMETER_DIGEST', E'WEEKLY', E'PRO_WEEKLY_BODY_PARAMETER_FEEDBACK', NULL::integer, TIME '17:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Max', E'WEIGHT_REMINDER', E'DAILY', E'MAX_WAKE_UP_SCALE_READING', NULL::integer, TIME '07:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'WORKOUT_NUDGE', E'DAILY', E'MAX_WORKOUT_NUDGE_MUSIC', NULL::integer, TIME '07:30', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, TRUE),
    (E'Max', E'BREAKFAST_REMINDER', E'DAILY', E'MAX_BREAKFAST_CUE_SWAPS', NULL::integer, TIME '08:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'HYDRATION_REMINDER', E'HOURLY', E'MAX_HOURLY_HYDRATION_HABIT_LOOP', NULL::integer, NULL::time, TIME '08:00', TIME '20:00', 60, NULL::integer, FALSE, FALSE),
    (E'Max', E'WEEKLY_MEAL_PLAN', E'WEEKLY', E'MAX_WEEKLY_CUSTOM_MEAL_PLAN_DELIVERY', NULL::integer, TIME '18:00', NULL::time, NULL::time, NULL::integer, 0, TRUE, FALSE),
    (E'Max', E'LUNCH_GUIDE', E'DAILY', E'MAX_NOURISHING_LUNCH_GUIDE', NULL::integer, TIME '13:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'SUPPLEMENT_REMINDER', E'DAILY', E'MAX_MICRONUTRIENT_REMINDER', NULL::integer, TIME '14:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'PREP_NUDGE', E'DAILY', E'MAX_PREP_ACTIVE_SWAP_NUDGE', NULL::integer, TIME '19:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'HABIT_AUDIT', E'DAILY', E'MAX_DAILY_HABIT_AUDIT_CHECK_IN', NULL::integer, TIME '22:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'GROCERY_STOCK_UP', E'WEEKLY', E'MAX_GROCERY_STOCK_UP', NULL::integer, TIME '10:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Max', E'PARAMETER_DIGEST', E'WEEKLY', E'MAX_WEEKLY_BODY_PARAMETER_FEEDBACK', NULL::integer, TIME '17:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Ultra', E'WEIGHT_REMINDER', E'DAILY', E'ULTRA_WAKE_UP_SCALE_READING', NULL::integer, TIME '07:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'HYDRATION_REMINDER', E'HOURLY', E'ULTRA_HOURLY_CONCIERGE_HYDRATION_SYNC', NULL::integer, NULL::time, TIME '08:00', TIME '20:00', 60, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'WEEKLY_MEAL_PLAN', E'WEEKLY', E'ULTRA_WEEKLY_EXECUTIVE_CONCIERGE_MEAL_PLAN_DELIVERY', NULL::integer, TIME '18:00', NULL::time, NULL::time, NULL::integer, 0, TRUE, FALSE),
    (E'Ultra', E'LUNCH_GUIDE', E'DAILY', E'ULTRA_NOURISHING_LUNCH_GUIDE', NULL::integer, TIME '13:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'SUPPLEMENT_REMINDER', E'DAILY', E'ULTRA_CLINICAL_SUPPLEMENT_REMINDER', NULL::integer, TIME '14:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'PREP_STRATEGY_CARD', E'DAILY', E'ULTRA_NEXT_DAY_PREP_STRATEGY_CARD', NULL::integer, TIME '19:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'SLEEP_WIND_DOWN', E'DAILY', E'ULTRA_EVENING_SLEEP_WIND_DOWN', NULL::integer, TIME '22:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, TRUE),
    (E'Ultra', E'PARAMETER_DIGEST', E'WEEKLY', E'ULTRA_WEEKLY_BODY_PARAMETER_FEEDBACK', NULL::integer, TIME '17:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE)
)
UPDATE message_schedules AS ms
SET template_id = tp.template_id,
    day_offset = d.day_offset,
    send_time = d.send_time,
    start_time = d.start_time,
    end_time = d.end_time,
    interval_minutes = d.interval_minutes,
    day_of_week = d.day_of_week,
    is_active = FALSE,
    updated_at = CURRENT_TIMESTAMP
FROM desired AS d
JOIN tiers AS t ON t.tier_name = d.tier_name
JOIN templates AS tp ON tp.template_code = d.template_code
WHERE ms.tier_id = t.tier_id
  AND ms.phase_id IS NULL
  AND ms.task_type = d.task_type
  AND ms.schedule_type = d.schedule_type
  AND (NOT d.requires_media OR tp.media_url IS NOT NULL)
  AND (
      NOT d.requires_resolved_vars
      OR (
          POSITION('{{spotify_max_link}}' IN tp.message_content) = 0
          AND POSITION('{{apple_max_link}}' IN tp.message_content) = 0
          AND POSITION('{{neural_audio_link}}' IN tp.message_content) = 0
      )
  );

-- Disable any already-existing targeted schedule whose required media/link is absent.
WITH desired(
    tier_name, task_type, schedule_type, template_code, day_offset,
    send_time, start_time, end_time, interval_minutes, day_of_week,
    requires_media, requires_resolved_vars
) AS (
    VALUES
    (E'Foundation', E'WEIGHT_REMINDER', E'DAILY', E'FOUNDATION_WAKE_UP_SCALE_READING', NULL::integer, TIME '07:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Foundation', E'LUNCH_GUIDE', E'DAILY', E'FOUNDATION_NOURISHING_LUNCH_GUIDE', NULL::integer, TIME '12:30', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Foundation', E'GREENS_NUDGE', E'WEEKLY', E'FOUNDATION_WEEKLY_GROCERY_STOCK_UP', NULL::integer, TIME '10:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Foundation', E'PARAMETER_DIGEST', E'WEEKLY', E'FOUNDATION_WEEKLY_BODY_PARAMETER_FEEDBACK', NULL::integer, TIME '17:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Pro', E'WEIGHT_REMINDER', E'DAILY', E'PRO_WAKE_UP_SCALE_READING', NULL::integer, TIME '07:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'FASTED_ACTIVITY', E'DAILY', E'PRO_ACTIVITY_CUE_BRANCH_A', NULL::integer, TIME '07:30', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'BREAKFAST_REMINDER', E'DAILY', E'PRO_BREAKFAST_CUE_BRANCH_B', NULL::integer, TIME '08:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'HYDRATION_REMINDER', E'HOURLY', E'PRO_HOURLY_OSMOTIC_HYDRATION_CHECK', NULL::integer, NULL::time, TIME '08:00', TIME '20:00', 60, NULL::integer, FALSE, FALSE),
    (E'Pro', E'FORTNIGHTLY_MEAL_PLAN', E'FORTNIGHTLY', E'PRO_FORTNIGHTLY_METABOLIC_MEAL_PLAN_DELIVERY', 1, TIME '09:00', NULL::time, NULL::time, NULL::integer, NULL::integer, TRUE, FALSE),
    (E'Pro', E'LUNCH_GUIDE', E'DAILY', E'PRO_NOURISHING_LUNCH_GUIDE', NULL::integer, TIME '13:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'SUPPLEMENT_REMINDER', E'DAILY', E'PRO_CLINICAL_SUPPLEMENT_REMINDER', NULL::integer, TIME '14:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'PREP_NUDGE', E'DAILY', E'PRO_NEXT_DAY_PREP_NUDGE', NULL::integer, TIME '19:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'SLEEP_WIND_DOWN', E'DAILY', E'PRO_EVENING_SLEEP_WIND_DOWN', NULL::integer, TIME '22:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'GROCERY_STOCK_UP', E'WEEKLY', E'PRO_WEEKLY_GROCERY_STOCK_UP', NULL::integer, TIME '10:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Pro', E'PARAMETER_DIGEST', E'WEEKLY', E'PRO_WEEKLY_BODY_PARAMETER_FEEDBACK', NULL::integer, TIME '17:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Max', E'WEIGHT_REMINDER', E'DAILY', E'MAX_WAKE_UP_SCALE_READING', NULL::integer, TIME '07:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'WORKOUT_NUDGE', E'DAILY', E'MAX_WORKOUT_NUDGE_MUSIC', NULL::integer, TIME '07:30', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, TRUE),
    (E'Max', E'BREAKFAST_REMINDER', E'DAILY', E'MAX_BREAKFAST_CUE_SWAPS', NULL::integer, TIME '08:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'HYDRATION_REMINDER', E'HOURLY', E'MAX_HOURLY_HYDRATION_HABIT_LOOP', NULL::integer, NULL::time, TIME '08:00', TIME '20:00', 60, NULL::integer, FALSE, FALSE),
    (E'Max', E'WEEKLY_MEAL_PLAN', E'WEEKLY', E'MAX_WEEKLY_CUSTOM_MEAL_PLAN_DELIVERY', NULL::integer, TIME '18:00', NULL::time, NULL::time, NULL::integer, 0, TRUE, FALSE),
    (E'Max', E'LUNCH_GUIDE', E'DAILY', E'MAX_NOURISHING_LUNCH_GUIDE', NULL::integer, TIME '13:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'SUPPLEMENT_REMINDER', E'DAILY', E'MAX_MICRONUTRIENT_REMINDER', NULL::integer, TIME '14:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'PREP_NUDGE', E'DAILY', E'MAX_PREP_ACTIVE_SWAP_NUDGE', NULL::integer, TIME '19:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'HABIT_AUDIT', E'DAILY', E'MAX_DAILY_HABIT_AUDIT_CHECK_IN', NULL::integer, TIME '22:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'GROCERY_STOCK_UP', E'WEEKLY', E'MAX_GROCERY_STOCK_UP', NULL::integer, TIME '10:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Max', E'PARAMETER_DIGEST', E'WEEKLY', E'MAX_WEEKLY_BODY_PARAMETER_FEEDBACK', NULL::integer, TIME '17:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Ultra', E'WEIGHT_REMINDER', E'DAILY', E'ULTRA_WAKE_UP_SCALE_READING', NULL::integer, TIME '07:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'HYDRATION_REMINDER', E'HOURLY', E'ULTRA_HOURLY_CONCIERGE_HYDRATION_SYNC', NULL::integer, NULL::time, TIME '08:00', TIME '20:00', 60, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'WEEKLY_MEAL_PLAN', E'WEEKLY', E'ULTRA_WEEKLY_EXECUTIVE_CONCIERGE_MEAL_PLAN_DELIVERY', NULL::integer, TIME '18:00', NULL::time, NULL::time, NULL::integer, 0, TRUE, FALSE),
    (E'Ultra', E'LUNCH_GUIDE', E'DAILY', E'ULTRA_NOURISHING_LUNCH_GUIDE', NULL::integer, TIME '13:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'SUPPLEMENT_REMINDER', E'DAILY', E'ULTRA_CLINICAL_SUPPLEMENT_REMINDER', NULL::integer, TIME '14:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'PREP_STRATEGY_CARD', E'DAILY', E'ULTRA_NEXT_DAY_PREP_STRATEGY_CARD', NULL::integer, TIME '19:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'SLEEP_WIND_DOWN', E'DAILY', E'ULTRA_EVENING_SLEEP_WIND_DOWN', NULL::integer, TIME '22:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, TRUE),
    (E'Ultra', E'PARAMETER_DIGEST', E'WEEKLY', E'ULTRA_WEEKLY_BODY_PARAMETER_FEEDBACK', NULL::integer, TIME '17:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE)
)
UPDATE message_schedules AS ms
SET is_active = FALSE,
    updated_at = CURRENT_TIMESTAMP
FROM desired AS d
JOIN tiers AS t ON t.tier_name = d.tier_name
JOIN templates AS tp ON tp.template_code = d.template_code
WHERE (
        (d.requires_media = TRUE AND tp.media_url IS NULL)
        OR (
            d.requires_resolved_vars = TRUE
            AND (
                POSITION('{spotify_max_link}' IN tp.message_content) > 0
                OR POSITION('{apple_max_link}' IN tp.message_content) > 0
                OR POSITION('{neural_audio_link}' IN tp.message_content) > 0
            )
        )
      )
  AND ms.tier_id = t.tier_id
  AND ms.phase_id IS NULL
  AND ms.task_type = d.task_type
  AND ms.schedule_type = d.schedule_type;

-- Insert missing schedules. New rows are deliberately inactive.
-- Skip document schedules until the media_url exists, and link-dependent messages
-- until their placeholders have been replaced by actual URLs.
WITH desired(
    tier_name, task_type, schedule_type, template_code, day_offset,
    send_time, start_time, end_time, interval_minutes, day_of_week,
    requires_media, requires_resolved_vars
) AS (
    VALUES
    (E'Foundation', E'WEIGHT_REMINDER', E'DAILY', E'FOUNDATION_WAKE_UP_SCALE_READING', NULL::integer, TIME '07:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Foundation', E'LUNCH_GUIDE', E'DAILY', E'FOUNDATION_NOURISHING_LUNCH_GUIDE', NULL::integer, TIME '12:30', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Foundation', E'GREENS_NUDGE', E'WEEKLY', E'FOUNDATION_WEEKLY_GROCERY_STOCK_UP', NULL::integer, TIME '10:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Foundation', E'PARAMETER_DIGEST', E'WEEKLY', E'FOUNDATION_WEEKLY_BODY_PARAMETER_FEEDBACK', NULL::integer, TIME '17:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Pro', E'WEIGHT_REMINDER', E'DAILY', E'PRO_WAKE_UP_SCALE_READING', NULL::integer, TIME '07:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'FASTED_ACTIVITY', E'DAILY', E'PRO_ACTIVITY_CUE_BRANCH_A', NULL::integer, TIME '07:30', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'BREAKFAST_REMINDER', E'DAILY', E'PRO_BREAKFAST_CUE_BRANCH_B', NULL::integer, TIME '08:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'HYDRATION_REMINDER', E'HOURLY', E'PRO_HOURLY_OSMOTIC_HYDRATION_CHECK', NULL::integer, NULL::time, TIME '08:00', TIME '20:00', 60, NULL::integer, FALSE, FALSE),
    (E'Pro', E'FORTNIGHTLY_MEAL_PLAN', E'FORTNIGHTLY', E'PRO_FORTNIGHTLY_METABOLIC_MEAL_PLAN_DELIVERY', 1, TIME '09:00', NULL::time, NULL::time, NULL::integer, NULL::integer, TRUE, FALSE),
    (E'Pro', E'LUNCH_GUIDE', E'DAILY', E'PRO_NOURISHING_LUNCH_GUIDE', NULL::integer, TIME '13:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'SUPPLEMENT_REMINDER', E'DAILY', E'PRO_CLINICAL_SUPPLEMENT_REMINDER', NULL::integer, TIME '14:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'PREP_NUDGE', E'DAILY', E'PRO_NEXT_DAY_PREP_NUDGE', NULL::integer, TIME '19:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'SLEEP_WIND_DOWN', E'DAILY', E'PRO_EVENING_SLEEP_WIND_DOWN', NULL::integer, TIME '22:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Pro', E'GROCERY_STOCK_UP', E'WEEKLY', E'PRO_WEEKLY_GROCERY_STOCK_UP', NULL::integer, TIME '10:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Pro', E'PARAMETER_DIGEST', E'WEEKLY', E'PRO_WEEKLY_BODY_PARAMETER_FEEDBACK', NULL::integer, TIME '17:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Max', E'WEIGHT_REMINDER', E'DAILY', E'MAX_WAKE_UP_SCALE_READING', NULL::integer, TIME '07:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'WORKOUT_NUDGE', E'DAILY', E'MAX_WORKOUT_NUDGE_MUSIC', NULL::integer, TIME '07:30', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, TRUE),
    (E'Max', E'BREAKFAST_REMINDER', E'DAILY', E'MAX_BREAKFAST_CUE_SWAPS', NULL::integer, TIME '08:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'HYDRATION_REMINDER', E'HOURLY', E'MAX_HOURLY_HYDRATION_HABIT_LOOP', NULL::integer, NULL::time, TIME '08:00', TIME '20:00', 60, NULL::integer, FALSE, FALSE),
    (E'Max', E'WEEKLY_MEAL_PLAN', E'WEEKLY', E'MAX_WEEKLY_CUSTOM_MEAL_PLAN_DELIVERY', NULL::integer, TIME '18:00', NULL::time, NULL::time, NULL::integer, 0, TRUE, FALSE),
    (E'Max', E'LUNCH_GUIDE', E'DAILY', E'MAX_NOURISHING_LUNCH_GUIDE', NULL::integer, TIME '13:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'SUPPLEMENT_REMINDER', E'DAILY', E'MAX_MICRONUTRIENT_REMINDER', NULL::integer, TIME '14:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'PREP_NUDGE', E'DAILY', E'MAX_PREP_ACTIVE_SWAP_NUDGE', NULL::integer, TIME '19:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'HABIT_AUDIT', E'DAILY', E'MAX_DAILY_HABIT_AUDIT_CHECK_IN', NULL::integer, TIME '22:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Max', E'GROCERY_STOCK_UP', E'WEEKLY', E'MAX_GROCERY_STOCK_UP', NULL::integer, TIME '10:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Max', E'PARAMETER_DIGEST', E'WEEKLY', E'MAX_WEEKLY_BODY_PARAMETER_FEEDBACK', NULL::integer, TIME '17:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE),
    (E'Ultra', E'WEIGHT_REMINDER', E'DAILY', E'ULTRA_WAKE_UP_SCALE_READING', NULL::integer, TIME '07:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'HYDRATION_REMINDER', E'HOURLY', E'ULTRA_HOURLY_CONCIERGE_HYDRATION_SYNC', NULL::integer, NULL::time, TIME '08:00', TIME '20:00', 60, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'WEEKLY_MEAL_PLAN', E'WEEKLY', E'ULTRA_WEEKLY_EXECUTIVE_CONCIERGE_MEAL_PLAN_DELIVERY', NULL::integer, TIME '18:00', NULL::time, NULL::time, NULL::integer, 0, TRUE, FALSE),
    (E'Ultra', E'LUNCH_GUIDE', E'DAILY', E'ULTRA_NOURISHING_LUNCH_GUIDE', NULL::integer, TIME '13:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'SUPPLEMENT_REMINDER', E'DAILY', E'ULTRA_CLINICAL_SUPPLEMENT_REMINDER', NULL::integer, TIME '14:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'PREP_STRATEGY_CARD', E'DAILY', E'ULTRA_NEXT_DAY_PREP_STRATEGY_CARD', NULL::integer, TIME '19:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, FALSE),
    (E'Ultra', E'SLEEP_WIND_DOWN', E'DAILY', E'ULTRA_EVENING_SLEEP_WIND_DOWN', NULL::integer, TIME '22:00', NULL::time, NULL::time, NULL::integer, NULL::integer, FALSE, TRUE),
    (E'Ultra', E'PARAMETER_DIGEST', E'WEEKLY', E'ULTRA_WEEKLY_BODY_PARAMETER_FEEDBACK', NULL::integer, TIME '17:00', NULL::time, NULL::time, NULL::integer, 6, FALSE, FALSE)
)
INSERT INTO message_schedules (
    tier_id, phase_id, day_offset, task_type, template_id, schedule_type,
    send_time, start_time, end_time, interval_minutes, day_of_week, is_active
)
SELECT
    t.tier_id,
    NULL,
    d.day_offset,
    d.task_type,
    tp.template_id,
    d.schedule_type,
    d.send_time,
    d.start_time,
    d.end_time,
    d.interval_minutes,
    d.day_of_week,
    FALSE
FROM desired AS d
JOIN tiers AS t ON t.tier_name = d.tier_name
JOIN templates AS tp ON tp.template_code = d.template_code
WHERE (NOT d.requires_media OR tp.media_url IS NOT NULL)
  AND (
      NOT d.requires_resolved_vars
      OR (
          POSITION('{{spotify_max_link}}' IN tp.message_content) = 0
          AND POSITION('{{apple_max_link}}' IN tp.message_content) = 0
          AND POSITION('{{neural_audio_link}}' IN tp.message_content) = 0
      )
  )
  AND NOT EXISTS (
      SELECT 1
      FROM message_schedules AS existing
      WHERE existing.tier_id = t.tier_id
        AND existing.phase_id IS NULL
        AND existing.task_type = d.task_type
        AND existing.schedule_type = d.schedule_type
  );

COMMIT;

-- ============================================================
-- POST-SEED VERIFICATION OUTPUT
-- ============================================================

SELECT
    split_part(template_code, '_', 1) AS tier_prefix,
    message_type,
    COUNT(*) AS template_count,
    COUNT(*) FILTER (WHERE media_url IS NOT NULL) AS templates_with_media
FROM templates
WHERE template_code LIKE 'FOUNDATION_%'
   OR template_code LIKE 'PRO_%'
   OR template_code LIKE 'MAX_%'
   OR template_code LIKE 'ULTRA_%'
GROUP BY 1, 2
ORDER BY 1, 2;

SELECT
    t.tier_name,
    ms.schedule_id,
    ms.task_type,
    ms.schedule_type,
    ms.day_offset,
    ms.send_time,
    ms.start_time,
    ms.end_time,
    ms.interval_minutes,
    ms.day_of_week,
    ms.is_active,
    tp.template_code,
    tp.message_type,
    (tp.media_url IS NOT NULL) AS has_media
FROM message_schedules ms
JOIN tiers t ON t.tier_id = ms.tier_id
JOIN templates tp ON tp.template_id = ms.template_id
WHERE t.tier_name IN ('Foundation', 'Pro', 'Max', 'Ultra')
  AND (
      tp.template_code LIKE 'FOUNDATION_%'
      OR tp.template_code LIKE 'PRO_%'
      OR tp.template_code LIKE 'MAX_%'
      OR tp.template_code LIKE 'ULTRA_%'
  )
ORDER BY t.tier_id, ms.schedule_id;

SELECT
    template_code,
    message_type,
    (media_url IS NOT NULL) AS has_media_url,
    message_content
FROM templates
WHERE message_type = 'DOCUMENT'
  AND (
      template_code LIKE 'FOUNDATION_%'
      OR template_code LIKE 'PRO_%'
      OR template_code LIKE 'MAX_%'
      OR template_code LIKE 'ULTRA_%'
  )
ORDER BY template_code;

UPDATE message_schedules
SET is_active = TRUE,
    updated_at = CURRENT_TIMESTAMP
WHERE is_active = FALSE;



