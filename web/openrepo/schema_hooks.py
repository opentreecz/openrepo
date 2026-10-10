"""drf-spectacular postprocessing hooks for OpenAPI schema customization."""


def add_global_error_responses(result, generator, **kwargs):
    """Inject 401 and 403 responses into all authenticated endpoints."""
    error_401 = {
        "description": "Authentication credentials were not provided or are invalid.",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "detail": {"type": "string", "example": "Authentication credentials were not provided."},
                    },
                },
            },
        },
    }
    error_403 = {
        "description": "You do not have permission to perform this action.",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "detail": {"type": "string", "example": "You do not have permission to perform this action."},
                    },
                },
            },
        },
    }

    # Paths that do not require authentication
    public_paths = {"/api/health/", "/api/schema/", "/api/docs/"}

    for path, methods in result.get("paths", {}).items():
        if path in public_paths:
            continue
        for method, operation in methods.items():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            if "401" not in operation["responses"]:
                operation["responses"]["401"] = error_401
            if "403" not in operation["responses"]:
                operation["responses"]["403"] = error_403

    return result
