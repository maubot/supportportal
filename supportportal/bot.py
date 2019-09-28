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
from typing import Type, Tuple, Dict, Optional, Set
import asyncio

from jinja2 import Environment as JinjaEnvironment
from sqlalchemy.ext.declarative import declarative_base

from mautrix.types import (EventType, StateEvent, PresenceEvent, ReactionEvent, MessageEvent,
                           RedactionEvent, RoomID, UserID, Member)
from mautrix.client import InternalEventType, MembershipEventDispatcher, SyncStream
from mautrix.util.db import BaseClass

from maubot import Plugin
from maubot.handlers import event, command

from .db import Case, ControlEvent, CaseAccept
from .config import Config, ConfigTemplateLoader

CLAIM_EMOJI = r"(?:\U0001F44D[\U0001F3FB-\U0001F3FF]?)"
REJECT_EMOJI = r"(?:\U0001F44E[\U0001F3FB-\U0001F3FF]?)"


class SupportPortalBot(Plugin):
    config: Config

    control_room: RoomID
    jinja_env: JinjaEnvironment
    config_load_id: int

    case: Type[Case]
    control_event: Type[ControlEvent]
    case_accept: Type[CaseAccept]

    cases: Dict[RoomID, Case]
    room_members: Dict[RoomID, Dict[UserID, Member]]
    agents: Set[UserID]

    async def start(self) -> None:
        self.client.add_dispatcher(MembershipEventDispatcher)

        self.config.load_and_update()
        self.control_room = self.config["control_room"]

        loader = ConfigTemplateLoader(self.config)
        self.jinja_env = JinjaEnvironment(loader=loader)

        base = declarative_base(cls=BaseClass, bind=self.database)
        self.case = Case.copy(bind=self.database, rebase=base)
        self.control_event = ControlEvent.copy(bind=self.database, rebase=base)
        self.case_accept = CaseAccept.copy(bind=self.database, rebase=base)
        base.metadata.create_all()

        self.agents = {}

        await self.update_agents()

        self.room_members = {}
        self.cases = {}

    def on_external_config_update(self) -> None:
        self.config.load_and_update()
        self.control_room = self.config["control_room"]
        self.jinja_env.loader.reload()
        asyncio.ensure_future(self.update_agents(), loop=self.loop)

    async def update_agents(self) -> None:
        if self.control_room:
            self.agents = set((await self.client.get_joined_members(self.control_room)).keys())
            self.agents.remove(self.client.mxid)

    @classmethod
    def get_config_class(cls) -> Type[Config]:
        return Config

    def render(self, template: str, **kwargs) -> str:
        return self.jinja_env.get_template(template).render(**kwargs)

    def get_case(self, room_id: RoomID) -> Optional[Case]:
        try:
            return self.cases[room_id]
        except KeyError:
            case = self.case.get(room_id)
            if case:
                self.cases[case.id] = case
                return case
        return None

    async def get_room_members(self, room_id: RoomID) -> Dict[UserID, Member]:
        try:
            return self.room_members[room_id]
        except KeyError:
            self.room_members[room_id] = await self.client.get_joined_members(room_id)
            return self.room_members[room_id]

    @event.on(InternalEventType.INVITE)
    async def self_invite_handler(self, evt: StateEvent) -> None:
        if evt.state_key != self.client.mxid or not evt.source & SyncStream.INVITED_ROOM:
            return
        elif self.control_room is None:
            await self.client.join_room_by_id(evt.room_id)
            await self.client.send_text(evt.room_id, "Room registered as the control room")
            self.control_room = self.config["control_room"] = evt.room_id
            await self.update_agents()
            self.config.save()
            return

        try:
            await self.client.join_room_by_id(evt.room_id)
            member = await self.client.get_state_event(evt.room_id, EventType.ROOM_MEMBER,
                                                       evt.sender)
            case = self.case(id=evt.room_id, user_id=evt.sender,
                             displayname=member.displayname)
            case.insert()
            self.cases[evt.room_id] = case
            await self.client.send_markdown(evt.room_id, self.render("welcome", evt=evt, case=case))
        except Exception:
            self.log.exception(f"Failed to handle invite from {evt.sender}")
            await self.client.send_markdown(self.control_room, self.render("invite_error", evt=evt))
            return
        event_id = await self.client.send_markdown(self.control_room,
                                                   self.render("new_case", evt=evt, case=case))
        self.control_event(event_id=event_id, case=evt.room_id, index=0).insert()

    @event.on(InternalEventType.JOIN)
    async def agent_join_handler(self, evt: StateEvent) -> None:
        if evt.state_key == self.client.mxid or evt.state_key not in self.agents:
            return
        print("Agent join:", evt)
        case = self.get_case(evt.room_id)
        if case:
            members = await self.get_room_members(evt.room_id)
            members[evt.sender] = evt.content

            await self.update_case_status(case, members)

    @event.on(InternalEventType.LEAVE)
    async def agent_leave_handler(self, evt: StateEvent) -> None:
        if evt.state_key == self.client.mxid or evt.state_key not in self.agents:
            return
        print("Agent leave:", evt)
        case = self.get_case(evt.room_id)
        if case:
            ctrl = self.control_event.latest_for_case(case.id)
            if ctrl:
                accept = self.case_accept.get_by_ctrl(ctrl.event_id, evt.sender)
                if accept:
                    await self.client.redact(self.control_room, accept.event_id, "Agent left room")
                    accept.delete()

            members = await self.get_room_members(evt.room_id)
            try:
                del members[evt.sender]
            except KeyError:
                pass

            await self.update_case_status(case, members)

    async def update_case_status(self, case: Case, members: Dict[str, Member]) -> None:
        ctrl = self.control_event.latest_for_case(case.id)
        if not ctrl:
            self.log.warning("Tried to update case", case, "with no control event")
            return
        agents = {key: value for key, value in members.items() if key in self.agents}
        await self.client.send_markdown(room_id=self.control_room, edits=ctrl.event_id,
                                        markdown=self.render("case_status", case=case,
                                                             agents=agents))

    @event.on(InternalEventType.PROFILE_CHANGE)
    async def displayname_change_handler(self, evt: StateEvent) -> None:
        if evt.state_key == self.client.mxid:
            return
        case = self.get_case(evt.room_id)
        if case and case.user_id == evt.state_key:
            case.edit(displayname=evt.content.displayname)
            await self.update_case_status(case, await self.get_room_members(evt.room_id))

    @event.on(EventType.ROOM_MESSAGE)
    async def case_message_handler(self, evt: MessageEvent) -> None:
        if evt.room_id == self.control_room or (evt.sender in self.agents
                                                or evt.sender == self.client.mxid):
            return
        case = self.get_case(evt.room_id)
        if not case:
            return
        members = await self.get_room_members(case.id)
        if len(members.keys() & self.agents) == 0:
            prev_ctrl = self.control_event.latest_for_case(case.id)
            if prev_ctrl:
                await self.client.redact(self.control_room, prev_ctrl.event_id,
                                         "Control event replaced")
                event_id = await self.client.send_markdown(
                    self.control_room, self.render("case_message", evt=evt, case=case))
                self.control_event(event_id=event_id, case=evt.room_id,
                                   index=(prev_ctrl.index + 1) if prev_ctrl else 0).insert()

    @event.on(EventType.PRESENCE)
    async def agent_presence_handler(self, evt: PresenceEvent) -> None:
        print("Presence:", evt.sender, evt.content)

    @command.passive(regex=CLAIM_EMOJI, field=lambda evt: evt.content.relates_to.key,
                     event_type=EventType.REACTION, msgtypes=None)
    async def claim_case(self, evt: ReactionEvent, key: Tuple[str]) -> None:
        if evt.room_id != self.control_room:
            return
        ctrl = self.control_event.get(evt.content.relates_to.event_id)
        if ctrl is None:
            return
        case = self.get_case(ctrl.case)
        await self.client.invite_user(case.id, evt.sender)
        self.case_accept(event_id=evt.event_id, control_event=ctrl.event_id, case=case.id,
                         user_id=evt.sender).insert()

        members = await self.get_room_members(case.id)
        # If we already have agents in the room, we don't want to edit to show
        # the case accepted message.
        if len(members.keys() & self.agents) == 0:
            member = await self.client.get_state_event(evt.room_id, EventType.ROOM_MEMBER,
                                                       evt.sender)
            await self.client.send_markdown(
                room_id=self.control_room, edits=ctrl.event_id,
                markdown=self.render("case_accepted", case=case, evt=evt,
                                     sender_displayname=member.displayname))

    @event.on(EventType.ROOM_REDACTION)
    async def redaction_handler(self, evt: RedactionEvent) -> None:
        if evt.room_id != self.control_room or evt.sender == self.client.mxid:
            return
        self.case_accept.delete_by_id(evt.redacts)

    @command.passive(regex=REJECT_EMOJI, field=lambda evt: evt.content.relates_to.key,
                     event_type=EventType.REACTION, msgtypes=None)
    async def reject_case(self, evt: ReactionEvent, key: Tuple[str]) -> None:
        if evt.room_id != self.control_room:
            return
        pass
