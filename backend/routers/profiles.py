from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from typing import List
from backend.database import async_session
from backend.models.profile import Profile
from backend.schemas.profile import ProfileCreate, ProfileResponse, ProfileUpdate, ProfileListResponse
from backend.agents.orchestrator import HistoriadorOrchestrator

router = APIRouter(prefix="/api/profiles", tags=["profiles"])
orchestrator = HistoriadorOrchestrator()

@router.get("", response_model=ProfileListResponse)
async def list_profiles():
    async with async_session() as session:
        result = await session.execute(select(Profile).order_by(Profile.created_at.desc()))
        profiles = result.scalars().all()
        return ProfileListResponse(
            profiles=[ProfileResponse(id=p.id, name=p.name, description=p.description, tone=p.tone, audience=p.audience, preferred_length=p.preferred_length, style_notes=p.style_notes, created_at=p.created_at, updated_at=p.updated_at) for p in profiles],
            total=len(profiles),
        )

@router.post("", response_model=ProfileResponse, status_code=201)
async def create_profile(body: ProfileCreate):
    async with async_session() as session:
        profile = Profile(name=body.name, description=body.description, tone=body.tone, audience=body.audience, preferred_length=body.preferred_length, style_notes=body.style_notes)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
        return ProfileResponse(id=profile.id, name=profile.name, description=profile.description, tone=profile.tone, audience=profile.audience, preferred_length=profile.preferred_length, style_notes=profile.style_notes, created_at=profile.created_at, updated_at=profile.updated_at)

@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile(profile_id: str):
    async with async_session() as session:
        profile = await session.get(Profile, profile_id)
        if not profile:
            raise HTTPException(404, "Profile not found")
        return ProfileResponse(id=profile.id, name=profile.name, description=profile.description, tone=profile.tone, audience=profile.audience, preferred_length=profile.preferred_length, style_notes=profile.style_notes, created_at=profile.created_at, updated_at=profile.updated_at)

@router.patch("/{profile_id}", response_model=ProfileResponse)
async def update_profile(profile_id: str, body: ProfileUpdate):
    async with async_session() as session:
        profile = await session.get(Profile, profile_id)
        if not profile:
            raise HTTPException(404, "Profile not found")
        for key, val in body.model_dump(exclude_unset=True).items():
            setattr(profile, key, val)
        await session.commit()
        await session.refresh(profile)
        return ProfileResponse(id=profile.id, name=profile.name, description=profile.description, tone=profile.tone, audience=profile.audience, preferred_length=profile.preferred_length, style_notes=profile.style_notes, created_at=profile.created_at, updated_at=profile.updated_at)