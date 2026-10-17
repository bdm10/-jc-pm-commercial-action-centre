"""Server-side access scope.

* sales    - customers currently assigned to them.
* manager  - customers assigned to members of the teams they manage (and their own).
* admin    - everything, plus configuration.

Assignment = latest in-app override if any, otherwise the imported baseline
valid today. Every customer-facing query goes through `Scope`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.models import facts as F
from app.models.records import AppUser, AssignmentOverride, TeamManager, TeamMember

CustomerKey = tuple[str, str]


def effective_assignees(db: Session, on: dt.date | None = None) -> dict[CustomerKey, int]:
    on = on or clock.today()
    by_code = {u.salesperson_code: u.id for u in db.execute(select(AppUser).where(AppUser.active.is_(True))).scalars()
               if u.salesperson_code}
    result: dict[CustomerKey, int] = {}
    chosen_from: dict[CustomerKey, dt.date] = {}
    rows = db.execute(
        select(F.Assignment).where(F.Assignment.valid_from <= on,
                                   (F.Assignment.valid_to.is_(None)) | (F.Assignment.valid_to >= on))
    ).scalars()
    for a in rows:
        key = (a.source_entity, a.source_customer_id)
        uid = by_code.get(a.salesperson_code)
        if uid is None:
            continue
        # If several baseline rows are valid, the most recent valid_from wins (also reported as a data issue on import).
        if key not in chosen_from or a.valid_from > chosen_from[key]:
            result[key], chosen_from[key] = uid, a.valid_from
    for o in db.execute(
        select(AssignmentOverride).where(AssignmentOverride.superseded_at.is_(None)).order_by(AssignmentOverride.id)
    ).scalars():
        result[(o.source_entity, o.source_customer_id)] = o.user_id
    return result


def managed_team_ids(db: Session, user_id: int) -> set[int]:
    return set(db.execute(select(TeamManager.team_id).where(TeamManager.user_id == user_id)).scalars())


def team_member_ids(db: Session, team_ids: set[int]) -> set[int]:
    if not team_ids:
        return set()
    return set(db.execute(select(TeamMember.user_id).where(TeamMember.team_id.in_(team_ids))).scalars())


@dataclass
class Scope:
    user: AppUser
    visible_user_ids: set[int] | None  # None = unrestricted (admin)
    assignees: dict[CustomerKey, int]

    @property
    def is_admin(self) -> bool:
        return self.user.role == "admin"

    @property
    def is_manager(self) -> bool:
        return self.user.role == "manager"

    def can_see(self, entity: str, customer_id: str) -> bool:
        if self.visible_user_ids is None:
            return True
        assignee = self.assignees.get((entity, customer_id))
        return assignee is not None and assignee in self.visible_user_ids

    def visible_customers(self) -> set[CustomerKey] | None:
        """None means all customers (admin)."""
        if self.visible_user_ids is None:
            return None
        return {k for k, uid in self.assignees.items() if uid in self.visible_user_ids}

    def can_assign_to(self, target: AppUser) -> bool:
        if not target.active or target.role not in ("sales", "manager"):
            return False
        if self.visible_user_ids is None:
            return True
        return self.is_manager and target.id in self.visible_user_ids


def build_scope(db: Session, user: AppUser) -> Scope:
    assignees = effective_assignees(db)
    if user.role == "admin":
        visible: set[int] | None = None
    elif user.role == "manager":
        visible = team_member_ids(db, managed_team_ids(db, user.id)) | {user.id}
    else:
        visible = {user.id}
    return Scope(user=user, visible_user_ids=visible, assignees=assignees)
