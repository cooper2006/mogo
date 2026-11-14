from fastapi import APIRouter

router = APIRouter()


@router.get("/meta")
async def meta() -> dict[str, object]:
    return {
        "product": "MOGO Admin",
        "mode": "shell",
        "modules": [
            "organizations",
            "models",
            "skills",
            "workflows",
            "tools",
            "settings",
            "analytics",
        ],
    }
