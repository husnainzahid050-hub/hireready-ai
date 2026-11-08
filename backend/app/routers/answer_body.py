"""Body handling for `POST /sessions/{id}/interview/answer`, which accepts JSON or multipart.

FastAPI can't declare "either a JSON model or a form" on one route, so the route takes the raw
Request and we validate here. JSON errors keep the exact 422 envelope FastAPI produced before
(`Invalid input: body.text`), so the text-mode contract is unchanged. `ANSWER_OPENAPI` documents
both body types in /docs.
"""

from typing import Any, Final

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.schemas.interview import AnswerRequest


def is_multipart(request: Request) -> bool:
    return request.headers.get("content-type", "").lower().startswith("multipart/form-data")


async def parse_json_answer(request: Request) -> AnswerRequest:
    try:
        payload = await request.json()
    except ValueError as exc:
        raise RequestValidationError([{"loc": ("body",), "msg": "Invalid JSON"}]) from exc
    try:
        return AnswerRequest.model_validate(payload)
    except ValidationError as exc:
        errors = [{**e, "loc": ("body", *e["loc"])} for e in exc.errors(include_input=False)]
        raise RequestValidationError(errors) from exc


ANSWER_OPENAPI: Final[dict[str, Any]] = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": AnswerRequest.model_json_schema()},
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["question_id", "audio"],
                    "properties": {
                        "question_id": {"type": "string", "format": "uuid"},
                        "audio": {
                            "type": "string",
                            "format": "binary",
                            "description": "webm/opus, ogg, mp4/m4a, wav, mp3 or flac; "
                            "max 3 MB and 120 s. Never stored.",
                        },
                    },
                }
            },
        },
    }
}
