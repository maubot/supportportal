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
from typing import Callable, Awaitable, Union, TYPE_CHECKING

from mautrix.types import StateEvent, MessageEvent

from .db import Case

if TYPE_CHECKING:
    from .bot import SupportPortalBot

RoomEvent = Union[StateEvent, MessageEvent]
EventHandler = Callable[['SupportPortalBot', RoomEvent], Awaitable[None]]
CasefulEventHandler = Callable[['SupportPortalBot', RoomEvent, Case], Awaitable[None]]


def with_case(func: CasefulEventHandler) -> EventHandler:
    @lock_room
    async def caseful_handler(self: 'SupportPortalBot', evt: RoomEvent) -> None:
        case = self.get_case(evt.room_id)
        if case:
            return await func(self, evt, case)

    return caseful_handler


def lock_room(func: EventHandler) -> EventHandler:
    async def locked_handler(self: 'SupportPortalBot', evt: RoomEvent) -> None:
        async with self.locks[evt.room_id]:
            return await func(self, evt)

    return locked_handler


def ignore_control_bot(func: EventHandler) -> EventHandler:
    async def ignoring_handler(self: 'SupportPortalBot', evt: RoomEvent) -> None:
        if evt.state_key == self.client.mxid:
            return
        await func(self, evt)

    return ignoring_handler
