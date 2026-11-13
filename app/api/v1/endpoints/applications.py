"""API endpoints for application processing and submission."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.orchestration.exceptions import (
    IdempotencyConflictError,
    InvalidStateTransitionError,
    InvalidWorkflowConfigError,
    OrchestrationError,
    WorkflowNotFoundError,
)
from app.orchestration.orchestrator import orchestrator
from app.schemas.application import ApplicationCreateRequest, ApplicationResponse

router = APIRouter()


@router.post(
    "/",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit and Process Application",
    description="Submit an application to be evaluated against the configured workflow rules.",
)
def submit_application(
    submission: ApplicationCreateRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    """Submit an application for workflow evaluation and atomic persistence."""
    try:
        result = orchestrator.process_application(db, submission)
        if result.is_idempotent_replay:
            response.status_code = status.HTTP_200_OK
        else:
            response.status_code = status.HTTP_201_CREATED
        return result.to_response()
    except WorkflowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except IdempotencyConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except InvalidWorkflowConfigError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
    except InvalidStateTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except OrchestrationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

