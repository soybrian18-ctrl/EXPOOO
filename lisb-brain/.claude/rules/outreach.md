# Outreach Rules

## Target Niches
Med spas and aesthetic clinics, luxury auto detailers, high-end landscapers and hardscapers, boutique fitness studios, wedding and portrait photographers, masonry.

## Qualifying Criteria
200 to 10,000 followers. Active within the last 30 to 60 days. Long Island based.

## Outreach Sequence
Follow, then like 2 to 3 posts, then Comment 1, then wait 1 to 2 days, then Comment 2 on a different post, then wait, then DM, then one follow-up bump maximum, then close the thread.
Portfolio sample mapping: boutique fitness and pilates studios point to the Apex Studios portfolio sample.

## Cold DM Voice
Open with one specific observation proving the page was read. One sentence only. Reference something visible: a specific service, a recent result, a post detail, an award, or a pattern across their content.

Second sentence: connect their momentum or quality to the offer naturally. Do not say 'the brand doesn't communicate that level yet' or any variation of it. Frame it as an opportunity, not a gap.

Third sentence: the offer. Keep it short. Logos, flyers, social templates, fully editable. Do not list every detail.

Closing line: a soft question that invites a reply. Vary it every time. Options include: 'Want to see what we'd put together for you?', 'Want to see a sample for your niche?', 'Want to see what we'd build for a practice like yours?', 'Curious what this would look like for your business?'

Hard rules:
- Under 75 words total
- Never use the same closing line twice in a row
- Never use the phrase 'doesn't communicate that level yet' or any variation
- No formal language. Write like a person texting, not a consultant emailing.
- Contractions required. We've, you've, that's, it's.
- Never paste the same offer block word for word across DMs. The offer line must vary.
- No em dashes. No banned words.

## Comment Rules
Reference something specific and visible in that exact post only. Never use location, LI, years in business, or bio details. Never duplicate a comment across accounts. 5 to 10 words. One emoji at the end only. Sound like a genuine peer reaction. If the comment could be left on any other account in the same niche, rewrite it.

## Soft Rejection Response
Remove pressure, plant a future follow-up, and signal selectivity by noting we only take a few clients at a time to keep quality tight.

## Profile Credibility Standards
The follower to following ratio matters to prospects. A high following count relative to followers signals a new or struggling account.

Target: following count must stay under 150 at all times. Unfollow any account that has not followed back after 30 days.

Follower growth priority: accounts already in the warm-up sequence are the most likely to follow back. A second genuine comment on a recent post increases the chance they tap the profile and follow.

Do not send a cold DM to any account while the following count is more than double the follower count. Fix the ratio first.

## Tracker
The outreach pipeline runs on `lisb_outreach.db` (SQLite), not the Excel file.
All reads and writes go through `db.py` only.
The Excel file `LISB_Outreach_Tracker_v2.xlsx` is a frozen backup. Never edit it.

db.py functions:
- add_account(handle, business_name, niche)
- update_stage(handle, stage)
- log_action(handle, action_type, date, text, post_url)
- get_accounts_by_stage(stage)
- get_dm_ready()
- get_bump_ready()
- is_closed(handle)
- search(handle)

Valid stages: S0, S1_follow, S2_like, S3_comment1, S4_comment2, S5_dm, S6_bump, S7_warm, S8_closed
