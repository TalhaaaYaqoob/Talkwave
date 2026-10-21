"""Read-only plan status used by the UI to decide which features to show."""

from fastapi import APIRouter, Depends, HTTPException

from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.subscription import shared_subscription_service

router = APIRouter(prefix="/subscription")


@router.get("/status")
async def get_subscription_status(user: UserModel = Depends(get_user)):
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return await shared_subscription_service.get_subscription_info(
        user.selected_organization_id
    )


@router.get("/can-make-call")
async def check_can_make_call(user: UserModel = Depends(get_user)):
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return await shared_subscription_service.check_can_make_call(
        user.selected_organization_id
    )
