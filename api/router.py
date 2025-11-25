#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from fastapi import APIRouter

from api.server import router as server_router
from api.admin import router as admin_router
from api.auth import router as auth_router

api_router = APIRouter(prefix="/api")
api_router.include_router(admin_router, prefix="/admin", tags=["Admin"])
api_router.include_router(auth_router, prefix="/auth", tags=["Auth"])
api_router.include_router(server_router, prefix="/server", tags=["Server"])
