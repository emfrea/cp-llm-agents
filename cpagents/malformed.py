"""Generate structurally-invalid (malformed) solutions to test verifier robustness.

A correct verifier must reject all of these (FAIL) and never crash (ERROR),
regardless of constraint satisfaction.
"""


def _shape_sample(decision_variables, example_solution):
    if isinstance(example_solution, dict) and example_solution:
        return dict(example_solution)
    if decision_variables:
        return {k: 0 for k in decision_variables}
    return {}


def generate_malformed(decision_variables, example_solution):
    sample = _shape_sample(decision_variables, example_solution)
    if not sample:
        return []
    keys = list(sample.keys())
    out = [("empty_object", {})]
    if keys:
        missing = dict(sample); missing.pop(keys[0])
        out.append((f"missing_{keys[0]}", missing))
        nulled = dict(sample); nulled[keys[0]] = None
        out.append((f"null_{keys[0]}", nulled))
    for k in keys:
        v = sample[k]
        m = dict(sample)
        if isinstance(v, bool):
            m[k] = "true"
        elif isinstance(v, (int, float)):
            m[k] = "not_a_number"
        elif isinstance(v, str):
            m[k] = 12345
        elif isinstance(v, list):
            m[k] = 0
        else:
            m[k] = "wrong"
        out.append((f"wrongtype_{k}", m))
    return out
