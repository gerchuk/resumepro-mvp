from fastapi import APIRouter
router = APIRouter()

@router.get('/whoami')
def whoami():
    return {"user": "anonymous"}