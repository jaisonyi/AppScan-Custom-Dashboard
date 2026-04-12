# NOTE: This is a STUB endpoint. Pipeline BOM integration is not yet implemented.
# The data returned below is hardcoded sample data for UI development purposes only.
# When real integration is available, replace the return value with live data from
# the pipeline BOM service and remove the _stub fields and X-Stub-Data header.

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.security.dependencies import UserContext, get_current_user
from app.core.security.policy import assert_action_allowed

router = APIRouter()


@router.get("")
def list_pipeline_bom(user: Annotated[UserContext, Depends(get_current_user)]) -> JSONResponse:
    assert_action_allowed("view_pipeline_bom", user.role)
    data = [
        {
            "pipeline": "payments-ci",
            "stages": ["build", "sast", "sca", "deploy"],
            "components": ["python:3.12", "fastapi", "react"],
            "risk_score": 32,
            "_stub": True,
            "_stub_message": "Pipeline BOM integration is not yet implemented. This endpoint returns sample data.",
        }
    ]
    return JSONResponse(
        content=data,
        headers={"X-Stub-Data": "true"},
    )
