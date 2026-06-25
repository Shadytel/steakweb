-- =====================================================================
-- dev/schema.sql  --  BEST-GUESS RECONSTRUCTION (DEV ONLY)
-- =====================================================================
-- There is NO authoritative schema file in this repo. This table was
-- reconstructed by reading every SQL statement in steakweb.py and
-- inferring column types from how the code reads/binds each column.
--
-- Columns observed in steakweb.py and the reasoning behind each type:
--
--   extn        integer, the unique identifier for a row. create_extn
--               relies on asyncpg.UniqueViolationError when re-inserting
--               an existing extn, and every handler uses `WHERE extn = $1`
--               as the row key  ->  modeled as INTEGER PRIMARY KEY.
--
--   name        free text the customer chooses                -> TEXT.
--
--   userid      integer taken from the SAML session (`int(session['uid'])`)
--               and compared with `WHERE userid = $1`          -> INTEGER.
--
--   auth_code   a generated string (12 random digits, or a 24-char SIP
--               password). Stored/read as a string             -> TEXT.
--
--   publish     The code BINDS and COMPARES this as the Python *strings*
--               't' / 'f'  (e.g. create_extn does
--               `publish = 't' if data.get('publish') else 'f'` and then
--               passes that string as a query parameter; directory() does
--               `WHERE publish = 't'`; publish_extn sets `publish = 't'`).
--               A real BOOLEAN column would make asyncpg REJECT the string
--               parameter 't'/'f' (asyncpg requires a Python bool for a
--               bool column), so this must be a 1-char text type that
--               literally stores the bytes 't'/'f'.            -> CHAR(1).
--
--   switch      integer, nullable. Code uses `switch IS NULL`,
--               `switch IS NOT NULL`, and `switch = 11`         -> INTEGER NULL.
--
--   provisioned Same 't'/'f' string treatment as publish
--               (homepage admin query: `WHERE provisioned = 't'`) -> CHAR(1).
--
-- ASSUMPTIONS / NOTES:
--   * CHAR(1) (bpchar) is used instead of the internal "char" type because
--     asyncpg encodes/decodes bpchar as a Python str cleanly, which is
--     exactly what the code binds. ("char" with quotes would also store a
--     single byte but asyncpg's handling of it is less obvious; bpchar is
--     the safe, well-defined choice that satisfies the 't'/'f' contract.)
--   * Defaults below are guesses chosen so the app behaves sensibly in dev;
--     production may differ. create_extn never sets `switch` or `provisioned`,
--     so those need server-side defaults (switch -> NULL = TDM/unprovisioned,
--     provisioned -> 'f').
--   * No foreign keys / extra indexes are reconstructed because the code
--     does not depend on any.
-- =====================================================================

CREATE TABLE registered_extensions (
    extn        integer PRIMARY KEY,
    name        text    NOT NULL DEFAULT '',
    userid      integer,
    auth_code   text,
    publish     char(1) NOT NULL DEFAULT 'f',   -- stores 't' / 'f' (NOT boolean)
    switch      integer,                          -- nullable; 11 == SIP
    provisioned char(1) NOT NULL DEFAULT 'f'      -- stores 't' / 'f' (NOT boolean)
);
