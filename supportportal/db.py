# supportportal - A maubot plugin to manage customer support on Matrix.
# Copyright (C) 2019 Tulir Asokan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from typing import Optional, Iterable

from sqlalchemy import Column, String, Text, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declared_attr

from mautrix.types import RoomID, EventID, UserID
from mautrix.util.db import BaseClass


class Case(BaseClass):
    __tablename__ = "case"
    id: RoomID = Column(String(255), primary_key=True)
    user_id: UserID = Column(String(255), nullable=False)
    room_name: str = Column(Text, nullable=False)
    displayname: str = Column(Text, nullable=False)

    @classmethod
    def get(cls, room_id: RoomID) -> Optional['Case']:
        return cls._select_one_or_none(cls.c.id == room_id)


class ControlEvent(BaseClass):
    __tablename__ = "control_event"
    event_id: EventID = Column(String(255), primary_key=True)
    case: RoomID
    index: int = Column(Integer, nullable=False)

    @declared_attr
    def case(self) -> RoomID:
        return Column(String(255), ForeignKey("case.id", ondelete="CASCADE", onupdate="CASCADE"),
                      nullable=False)

    @classmethod
    def get(cls, event_id: EventID) -> Optional['ControlEvent']:
        return cls._select_one_or_none(cls.c.event_id == event_id)

    @classmethod
    def latest_for_case(cls, room_id: RoomID) -> Optional['ControlEvent']:
        return cls._one_or_none(cls.db.execute(cls._make_simple_select(cls.c.case == room_id)
                                               .order_by(cls.c.index.desc(), cls.c.event_id.desc())
                                               .limit(1)))

    @classmethod
    def all_for_case(cls, room_id: RoomID) -> Iterable['ControlEvent']:
        yield from cls._all(cls.db.execute(cls._make_simple_select(cls.c.case == room_id)
                                           .order_by(cls.c.index.desc(), cls.c.event_id.desc())))


class CaseAccept(BaseClass):
    __tablename__ = "case_accept"
    __table_args__ = (UniqueConstraint("control_event", "user_id"),)
    event_id: EventID = Column(String(255), primary_key=True)
    control_event: EventID = Column(String(255), nullable=False)
    case: RoomID = Column(String(255), nullable=False)
    user_id: UserID = Column(String(255), nullable=False)

    @classmethod
    def delete_by_id(cls, event_id: EventID) -> None:
        cls.db.execute(cls.t.delete().where(cls.c.event_id == event_id))

    @classmethod
    def delete_by_ctrl(cls, control_event: EventID, user_id: UserID) -> None:
        cls.db.execute(cls.t.delete().where(cls.c.control_event == control_event,
                                            cls.c.user_id == user_id))

    @classmethod
    def get_by_ctrl(cls, control_event: EventID, user_id: UserID) -> Optional['CaseAccept']:
        return cls._select_one_or_none(cls.c.control_event == control_event,
                                       cls.c.user_id == user_id)
