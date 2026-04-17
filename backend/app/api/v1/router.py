from fastapi import APIRouter

from app.api.v1.routes import (
	analytics,
	applications,
	asset_groups,
	audit,
	auth,
	dashboard,
	endpoints,
	exports,
	issues,
	pipeline_bom,
	reports,
	scans,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(scans.router, prefix="/scans", tags=["scans"])
api_router.include_router(applications.router, prefix="/applications", tags=["applications"])
api_router.include_router(asset_groups.router, prefix="/asset-groups", tags=["asset-groups"])
api_router.include_router(issues.router, prefix="/issues", tags=["issues"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(dashboard.router, prefix="/dashboards", tags=["dashboards"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(pipeline_bom.router, prefix="/pipeline-bom", tags=["pipeline-bom"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(endpoints.router, prefix="/endpoints", tags=["endpoints"])
api_router.include_router(exports.router, prefix="/export", tags=["export"])
