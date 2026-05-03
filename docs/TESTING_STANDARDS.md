# Testing Standards

## FastAPI Parameter Testing

FastAPI treats plain scalar handler arguments as query parameters unless the route declares a body model, `Body(...)`, or explicitly reads the request body. Tests must send those values with `params=`, not `json=`. A JSON body sent to a query-only route is ignored by FastAPI and can make a test pass while it is exercising the default query value.

Use this pattern for query parameters:

```python
resp = client.post(
    f"/api/diagrams/{diagram_id}/export-diagram",
    params={"format": "drawio"},
)
```

Use `json=` only for routes that declare a request body in the OpenAPI contract:

```python
resp = client.post(
    f"/api/diagrams/{diagram_id}/apply-answers",
    json={"answers": {}},
)
```

CI runs `backend/scripts/lint_fastapi_query_body_tests.py` to catch `json=` calls that target query-only FastAPI routes in `backend/tests/**/*.py` and `tests/**/*.py`.
