"""API endpoints for application processing, submission, and retries."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.orchestration.exceptions import (
    ApplicationNotFoundError,
    IdempotencyConflictError,
    IneligibleRetryError,
    InvalidStateTransitionError,
    InvalidWorkflowConfigError,
    OrchestrationError,
    RetryLimitExceededError,
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
    description="Submit an application to be evaluated against the configured workflow rules and external verification.",
)
def submit_application(
    submission: ApplicationCreateRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    """Submit an application for workflow evaluation, external verification, and persistence."""
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


@router.post(
    "/{application_id}/retry",
    response_model=ApplicationResponse,
    status_code=status.HTTP_200_OK,
    summary="Retry Application Processing",
    description="Retry an application currently in RETRY_PENDING status following a transient failure.",
)
def retry_application(
    application_id: int,
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    """Execute a retry attempt for an eligible application."""
    try:
        result = orchestrator.retry_application(db, application_id)
        return result.to_response()
    except ApplicationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except (IneligibleRetryError, RetryLimitExceededError, InvalidStateTransitionError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except OrchestrationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
