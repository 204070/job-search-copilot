-- Countries the user does not apply to, with the spellings a board uses.
--
-- A posting whose `location` or `region_evidence` matches one of these terms is
-- left out of the "Next roles" shortlist and the blind-spot table. The row is
-- NOT archived: the posting stays in the pool, so removing the country here
-- brings it back without a rescan.
--
-- This is data rather than code because the list is a judgement about where an
-- application can realistically convert, and it lives in the database rather
-- than a committed file because the reason names a country and the user's
-- situation. `terms` is a JSON array of case-insensitive regular expressions,
-- because one country has more than one spelling on these boards: "India",
-- "KA, IN | Bengaluru, KA, IN", and a city name that never says India at all.
-- Matching on the bare name is not enough, and matching on the two-letter code
-- alone would catch the English word.
CREATE TABLE skipped_countries (
    country_key TEXT PRIMARY KEY,
    terms TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(terms)),
    reason TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
