-- A second, tighter list of patterns for a skipped country, matched against the
-- posting text rather than the location field.
--
-- The first list (`terms`) reads `location` and `region_evidence`, where a board
-- puts the country and a place name almost always means the job sits there. The
-- ad text is different: a company names its offices, its team, and the places it
-- has customers, so "India" in a description proves nothing. Some boards leave
-- the location field empty and put the real place in the first line of the ad
-- ("Location - India (Remote)", "This is a fulltime position based in
-- Bangalore"), and those postings escaped the first list entirely.
--
-- So the text list holds only phrasings that declare where the work sits: a
-- city beside "based" or "located", a role noun beside "based in <country>",
-- "Remote - <country>", a location line that starts with the country. It is
-- applied only when the structured location says nothing at all, which keeps a
-- worldwide posting that mentions an office out of it.
ALTER TABLE skipped_countries
    ADD COLUMN terms_in_text TEXT NOT NULL DEFAULT '[]'
    CHECK (json_valid(terms_in_text));
