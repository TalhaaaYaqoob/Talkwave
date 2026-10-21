import asyncio
from typing import Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.pipecat.run_pipeline import run_pipeline_smallwebrtc
from api.services.security.rate_limiter import limiter, RateLimitTiers
from api.services.subscription.subscription_service import SubscriptionService
from api.services.webrtc import get_ice_servers_for_aiortc
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.utils.context import set_current_run_id

router = APIRouter(prefix="/pipecat")

pcs_map: Dict[str, SmallWebRTCConnection] = {}

# Subscription service for usage checks
_sub_service = SubscriptionService()


class RTCOfferRequest(BaseModel):
    pc_id: str | None
    sdp: str
    type: str
    workflow_id: int
    workflow_run_id: int
    restart_pc: bool = False
    call_context_vars: dict | None = None


@router.post("/rtc-offer")
@limiter.limit(RateLimitTiers.CRITICAL)  # Critical for real-time WebRTC communication
async def offer(
    request: Request,
    offer_request: RTCOfferRequest,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(get_user),
):
    pc_id = offer_request.pc_id

    if pc_id and pc_id in pcs_map:
        # Ensure run_id context is available for logs even when reusing an existing PC.
        set_current_run_id(offer_request.workflow_run_id)

        pipecat_connection = pcs_map[pc_id]
        logger.info(f"Reusing existing connection for pc_id: {pc_id}")
        await pipecat_connection.renegotiate(
            sdp=offer_request.sdp,
            type=offer_request.type,
            restart_pc=offer_request.restart_pc,
        )
    else:
        set_current_run_id(offer_request.workflow_run_id)

        pipecat_connection = SmallWebRTCConnection(get_ice_servers_for_aiortc())

        # LATENCY FIX: Run SDP init, subscription check, and workflow + run
        # pre-fetch ALL in parallel instead of sequentially (~1.2s instead of ~4.8s).
        sdp_init_task = pipecat_connection.initialize(
            sdp=offer_request.sdp, type=offer_request.type
        )
        sub_check_task = _sub_service.check_can_make_call(user.selected_organization_id)
        workflow_task = db_client.get_workflow(offer_request.workflow_id, user.id)
        run_task = db_client.get_workflow_run(offer_request.workflow_run_id, user.id)
        config_task = db_client.get_user_configurations(user.id)

        _, can_call, workflow, workflow_run, user_config = await asyncio.gather(
            sdp_init_task, sub_check_task, workflow_task, run_task, config_task
        )

        # Authorization: the workflow and run must exist, belong to the caller,
        # and be consistent with each other before we start an (expensive)
        # pipeline. This blocks IDOR/cross-tenant pipeline starts.
        if not workflow or not workflow_run:
            raise HTTPException(status_code=404, detail="Workflow or run not found")
        if workflow_run.workflow_id != offer_request.workflow_id:
            raise HTTPException(status_code=403, detail="Run does not match workflow")
        if (
            workflow.organization_id is not None
            and workflow.organization_id != user.selected_organization_id
        ):
            raise HTTPException(status_code=403, detail="Access denied")

        if not can_call["allowed"]:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "subscription_limit",
                    "reason": can_call["reason"],
                    "message": can_call.get("message", "Subscription limit reached"),
                },
            )

        @pipecat_connection.event_handler("closed")
        async def handle_disconnected(webrtc_connection: SmallWebRTCConnection):
            logger.info(
                f"In pipecat connection closed handler. Popping peer connection pc_id: {webrtc_connection.pc_id} from pcs_map"
            )
            pcs_map.pop(webrtc_connection.pc_id, None)

        background_tasks.add_task(
            run_pipeline_smallwebrtc,
            pipecat_connection,
            offer_request.workflow_id,
            offer_request.workflow_run_id,
            user.id,
            offer_request.call_context_vars or {},
            workflow=workflow,
            workflow_run=workflow_run,
            user_config=user_config,
        )

    answer = pipecat_connection.get_answer()
    pcs_map[answer["pc_id"]] = pipecat_connection

    return answer
