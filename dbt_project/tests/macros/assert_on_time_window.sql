-- Known answers for the WMATA on-time window at the default vars (120 s early,
-- 420 s late). Returns a row for every case that is wrong.

with cases as (
    select -121 as deviation_s, false as is_last, false as expected
    union all select -120, false, true
    union all select 420, false, true
    union all select 421, false, false
    -- Last timepoint: only lateness counts.
    union all select -900, true, true
    union all select 421, true, false
)

select *
from cases
where {{ is_on_time('deviation_s', 'is_last') }} <> expected
