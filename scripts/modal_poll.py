#!/usr/bin/env python3
"""State of Modal function calls by id, without waiting for them (lib/jobs.py's Modal backend runs
it with a Python that has modal; the active Modal profile, or MODAL_PROFILE, picks the workspace):
  <python with modal> modal_poll.py fc-... [fc-...]
Prints one JSON line per id: {"id", "state": running|finished|failed|unknown, "detail"}; detail is
the returned value (a pipeline may report its own failure in it) or the error, cut to 300 characters."""
import json
import sys
import time

import modal

for fc_id in sys.argv[1:]:
    t = time.time()
    try:
        call = modal.FunctionCall.from_id(fc_id)
        try:
            res = call.get(timeout=0)
            state, detail = "finished", repr(res)[:300]
        except TimeoutError:
            state, detail = "running", ""
        except modal.exception.OutputExpiredError as e:
            state, detail = "unknown", "result expired: %s" % e
    except modal.exception.NotFoundError as e:
        state, detail = "unknown", "not found: %s" % e
    except Exception as e:      # the call itself raised: the job failed
        state, detail = "failed", "%s: %s" % (type(e).__name__, str(e)[:300])
    print(json.dumps({"id": fc_id, "state": state, "detail": detail, "poll_s": round(time.time() - t, 2)}))
