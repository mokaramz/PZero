"""The inference gateway core (review 029a): one gateway for every model call, budget-checked per attempt and
ledgered per attempt, with NO live call enabled (paid calls run only when ``PZ_AI_PAID`` is exactly ``on`` and the
provider key is set; decision c).

Safety rails, enforced in code:
  * Nothing here reads or writes scores, decisions or any other Project Zero record: this layer moves text and
    accounts for money; callers own what a reply is used for.
  * Paid calls stop on the paid switch, any cap, a missing price and a missing key. Keys come from the environment
    only, at call time, and are never stored, logged or returned.
  * Retries are bounded (429 / 5xx / timeout / network only; never auth, billing or bad requests).
  * Under pytest a real provider refuses to run (decision b).
"""

from projectzero.core.inference.gateway import Result, complete, extract_json, status

__all__ = ["Result", "complete", "extract_json", "status"]
