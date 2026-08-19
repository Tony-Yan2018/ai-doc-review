from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .auth import hash_password, verify_password
from .api import router
from .config import get_settings
from .database import Base, SessionLocal, engine
from .models import Membership, MembershipRole, Tenant, User


DEMO_TENANTS = (
    ("11111111-1111-4111-8111-111111111111", "Acme Legal", "acme-legal"),
    ("22222222-2222-4222-8222-222222222222", "Northwind Policy", "northwind-policy"),
)

DEMO_PASSWORD = "DemoPass123!"
DEMO_USERS = (
    ("33333333-3333-4333-8333-333333333333", "owner@acme.local", "Acme Owner"),
    ("44444444-4444-4444-8444-444444444444", "reviewer@acme.local", "Acme Reviewer"),
    ("55555555-5555-4555-8555-555555555555", "viewer@northwind.local", "Northwind Viewer"),
)
DEMO_MEMBERSHIPS = (
    ("owner@acme.local", "acme-legal", MembershipRole.owner),
    ("owner@acme.local", "northwind-policy", MembershipRole.viewer),
    ("reviewer@acme.local", "acme-legal", MembershipRole.reviewer),
    ("viewer@northwind.local", "northwind-policy", MembershipRole.viewer),
)


def initialize_database() -> None:
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        tenants_by_slug = {tenant.slug: tenant for tenant in db.scalars(select(Tenant))}
        for tenant_id, name, slug in DEMO_TENANTS:
            if slug not in tenants_by_slug:
                tenant = Tenant(id=tenant_id, name=name, slug=slug)
                db.add(tenant)
                tenants_by_slug[slug] = tenant
        users_by_email = {user.email: user for user in db.scalars(select(User))}
        for user_id, email, full_name in DEMO_USERS:
            user = users_by_email.get(email)
            if user is None:
                user = User(
                    id=user_id,
                    email=email,
                    full_name=full_name,
                    password_hash=hash_password(DEMO_PASSWORD),
                )
                db.add(user)
                users_by_email[email] = user
            elif not verify_password(DEMO_PASSWORD, user.password_hash):
                user.password_hash = hash_password(DEMO_PASSWORD)
        db.flush()
        existing_memberships = {
            (membership.user_id, membership.tenant_id): membership
            for membership in db.scalars(select(Membership))
        }
        for email, tenant_slug, role in DEMO_MEMBERSHIPS:
            user = users_by_email[email]
            tenant = tenants_by_slug[tenant_slug]
            membership = existing_memberships.get((user.id, tenant.id))
            if membership is None:
                db.add(Membership(user_id=user.id, tenant_id=tenant.id, role=role))
            elif membership.role != role:
                membership.role = role
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    initialize_database()
    yield


app = FastAPI(title="AI Document Review API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
