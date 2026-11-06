-- One row per fetch attempt with feed-level checks.
--   failed_fetch   no usable response after retries
--   empty_feed     a 200 response with zero entities
--   stale_feed     header timestamp unchanged from the previous successful fetch
--   missed_polls   polls that should have happened since the previous fetch but did not
--                  (collector stopped, machine asleep, or a long retry)

with fetches as (
    select
        *,
        lag(fetch_epoch) over (partition by feed order by fetch_epoch) as prev_fetch_epoch,
        lag(header_epoch ignore nulls) over (partition by feed order by fetch_epoch)
            as prev_header_epoch
    from {{ ref('stg_collector__fetches') }}
)

select
    fetch_epoch,
    fetched_at,
    cast(fetched_at as date) as fetch_date,
    hour(fetched_at) as fetch_hour,
    feed,
    http_status,
    entity_count,
    header_age_s,
    fetch_epoch - prev_fetch_epoch as seconds_since_prev_fetch,
    http_status is distinct from 200 as failed_fetch,
    http_status = 200 and entity_count = 0 as empty_feed,
    coalesce(header_epoch = prev_header_epoch, false) as stale_feed,
    case
        when fetch_epoch - prev_fetch_epoch > {{ var('dq_feed_gap_s') }}
            then cast(round((fetch_epoch - prev_fetch_epoch) / 30.0) as integer) - 1
        else 0
    end as missed_polls
from fetches
