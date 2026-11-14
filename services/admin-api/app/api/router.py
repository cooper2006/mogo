from fastapi import APIRouter

from app.api.routes import analytics, auth, approval_todos, capability_assets, connector_market, dashboard, directory, dsh_plugins, egress, employees, external_search, gatekeeper_internal, governance, hooks, knowledge_directories, knowledge_documents, knowledge_settings, memories, menu_settings, models, ontologies, ontology_permission_internal, organizations, page_collection, personal_knowledge_internal, position_roles, portal_admin, presentation_settings, setup, shortcut_settings, skill_canary, skill_eval, skill_lifecycle, skill_monitoring, skills, system, system_audit, templates, tools, topic_admission, traffic_allocations, trust_ratings, compatibility
from app.api.routes.platform import tenants as platform_tenants

api_router = APIRouter()
api_router.include_router(system.router, tags=["system"])
api_router.include_router(setup.router, prefix="/setup", tags=["setup"])
api_router.include_router(platform_tenants.router, prefix="/platform", tags=["platform"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(organizations.router, prefix="/organizations", tags=["organizations"])
api_router.include_router(directory.router, prefix="/directory", tags=["directory"])
api_router.include_router(position_roles.router, prefix="/position-roles", tags=["position-roles"])
api_router.include_router(employees.router, prefix="/employees", tags=["employees"])
api_router.include_router(ontologies.router, prefix="/ontologies", tags=["ontologies"])
api_router.include_router(
    ontology_permission_internal.router,
    prefix="/internal/ontology-permissions",
    tags=["ontology-permission-internal"],
)
api_router.include_router(system_audit.router, prefix="/system-audit", tags=["system-audit"])
api_router.include_router(dsh_plugins.router, prefix="/dsh-plugins", tags=["dsh-plugins"])
api_router.include_router(topic_admission.router, prefix="/settings/topic-admission", tags=["topic-admission"])
api_router.include_router(models.router, prefix="/models", tags=["models"])
api_router.include_router(knowledge_directories.router, prefix="/knowledge/directories", tags=["knowledge-directories"])
api_router.include_router(knowledge_documents.router, prefix="/knowledge/documents", tags=["knowledge-documents"])
api_router.include_router(knowledge_settings.router, prefix="/settings/knowledge", tags=["knowledge-settings"])
api_router.include_router(personal_knowledge_internal.router, prefix="/internal/personal-knowledge", tags=["personal-knowledge-internal"])
api_router.include_router(gatekeeper_internal.router, prefix="/internal/gatekeeper", tags=["gatekeeper-internal"])
# 056 US1：统一审批待办（跨 tool/portal/sop 三来源的只读聚合视图）。
api_router.include_router(approval_todos.router, prefix="/admin/approvals", tags=["approval-todos"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(traffic_allocations.router, prefix="/traffic-allocations", tags=["traffic-allocations"])
api_router.include_router(skills.router, prefix="/skills", tags=["skills"])
api_router.include_router(skill_canary.router, tags=["skill-canary"])
api_router.include_router(skill_monitoring.router, tags=["skill-monitoring"])
api_router.include_router(capability_assets.router, prefix="/capabilities", tags=["capability-assets"])
api_router.include_router(capability_assets.admin_router, tags=["capability-assets-admin"])  # 045 FR-1：/api/v1/capabilities/list
api_router.include_router(skill_lifecycle.router, prefix="/skills", tags=["skills"])
api_router.include_router(skill_eval.router, prefix="/skills", tags=["skills"])
api_router.include_router(tools.router, prefix="/tools", tags=["tools"])
api_router.include_router(governance.router, tags=["governance"])
# 057: pg_compat 管线兼容端点。模块自身已带 prefix="/admin/compatibility"，
# 此处不再叠加 prefix，否则会拼成 /compatibility/admin/compatibility。
api_router.include_router(compatibility.api_router, tags=["compatibility"])
api_router.include_router(trust_ratings.router, tags=["trust-rating"])
api_router.include_router(portal_admin.router, tags=["portal"])
api_router.include_router(hooks.router, tags=["hooks"])
api_router.include_router(egress.router, tags=["egress"])
api_router.include_router(external_search.router, prefix="/settings/external-search", tags=["external-search"])
api_router.include_router(page_collection.router, prefix="/settings/page-collection", tags=["page-collection"])
api_router.include_router(presentation_settings.router, prefix="/settings/presentation", tags=["presentation-settings"])
api_router.include_router(shortcut_settings.router, prefix="/settings/shortcuts", tags=["shortcut-settings"])
api_router.include_router(menu_settings.router, prefix="/settings/menus", tags=["menu-settings"])  # 055 菜单管理
api_router.include_router(connector_market.router, prefix="/connectors", tags=["connectors"])
api_router.include_router(templates.router, prefix="/templates", tags=["templates"])  # 053-plaza-template-distribution
api_router.include_router(memories.router, prefix="/memories/admin", tags=["memories-admin"])  # 017 §9.1 治理端点
