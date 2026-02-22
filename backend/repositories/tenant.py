"""Tenant repositories for multi-tenancy CRUD (Issue #169)."""

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from repositories.base import BaseRepository
from models.tenant import Organization, TeamMember, Invitation

logger = logging.getLogger(__name__)


class OrganizationRepo(BaseRepository):
    model = Organization

    def get_by_org_id(self, org_id: str) -> Optional[Organization]:
        return self.db.query(Organization).filter_by(org_id=org_id).first()

    def get_by_slug(self, slug: str) -> Optional[Organization]:
        return self.db.query(Organization).filter_by(slug=slug).first()


class TeamMemberRepo(BaseRepository):
    model = TeamMember

    def get_members(self, org_id: str, active_only: bool = True) -> List[TeamMember]:
        q = self.db.query(TeamMember).filter_by(org_id=org_id)
        if active_only:
            q = q.filter_by(is_active=True)
        return q.all()

    def get_membership(self, org_id: str, user_id: str) -> Optional[TeamMember]:
        return self.db.query(TeamMember).filter_by(
            org_id=org_id, user_id=user_id
        ).first()

    def get_user_orgs(self, user_id: str) -> List[TeamMember]:
        return self.db.query(TeamMember).filter_by(
            user_id=user_id, is_active=True
        ).all()


class InvitationRepo(BaseRepository):
    model = Invitation

    def get_by_token(self, token: str) -> Optional[Invitation]:
        return self.db.query(Invitation).filter_by(token=token).first()

    def get_pending(self, org_id: str) -> List[Invitation]:
        return self.db.query(Invitation).filter_by(
            org_id=org_id, status="pending"
        ).all()
