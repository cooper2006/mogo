from __future__ import annotations

from typing import Iterable, Literal

from app.product.extensions import get_product_extension


ResourceType = Literal["skill", "tool", "plugin"]


async def filter_allowed_resource_ids(
    resource_type: ResourceType,
    *,
    main_id: str,
    user_id: str,
    resource_ids: Iterable[str],
) -> set[str]:
    """Apply the distribution-owned audience policy to organization assets.

    Community has no people-scoped resource ACL, so every organization asset
    passed to this boundary remains available. Private distributions may
    narrow the set without leaking their policy model into the OSS runtime.
    """

    ids = {str(item).strip() for item in resource_ids if str(item).strip()}
    if not ids:
        return set()
    policy = get_product_extension().resource_access_policy
    if policy is None:
        return ids
    allowed = await policy.filter_ids(
        resource_type=resource_type,
        main_id=str(main_id),
        user_id=str(user_id),
        resource_ids=sorted(ids),
    )
    return ids.intersection({str(item) for item in allowed})


async def resource_is_allowed(
    resource_type: ResourceType,
    *,
    main_id: str,
    user_id: str,
    resource_id: str,
) -> bool:
    target = str(resource_id or "").strip()
    if not target:
        return False
    return target in await filter_allowed_resource_ids(
        resource_type,
        main_id=main_id,
        user_id=user_id,
        resource_ids=(target,),
    )
