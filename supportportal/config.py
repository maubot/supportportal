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
from typing import Tuple, Iterable, Any, Callable

from jinja2 import BaseLoader, TemplateNotFound

from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("control_room")
        helper.copy("template_prepend")
        helper.copy_dict("templates")


class ConfigTemplateLoader(BaseLoader):
    config: Config
    prepend: str
    reload_counter: int

    def __init__(self, config: Config) -> None:
        self.config = config
        self.reload_counter = 0

    def reload(self) -> None:
        self.reload_counter += 1

    def get_source(self, environment: Any, template: str) -> Tuple[str, str, Callable[[], bool]]:
        cur_reload_counter = self.reload_counter
        try:
            return (self.config["template_prepend"] + self.config["templates"][template], template,
                    lambda: self.reload_counter == cur_reload_counter)
        except KeyError as e:
            raise TemplateNotFound(template)

    def list_templates(self) -> Iterable[str]:
        return sorted(self.config["templates"].keys())
