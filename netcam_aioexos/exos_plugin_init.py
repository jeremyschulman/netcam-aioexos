#  Copyright 2021 Jeremy Schulman
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from pydantic import ValidationError
import httpx

from .exos_plugin_globals import g_exos
from .exos_plugin_config import EXosPluginConfig


def plugin_init(plugin_def: dict):
    """
    This function is the required netcam plugin 'hook' that is called during the
    netcam tool initialization process.  The primary purpose of this function is
    to pass along the User defined configuration from the `netcad.toml` file.

    Parameters
    ----------
    plugin_def: dict
        The plugin definition as declared in the User `netcad.toml`
        configuration file.
    """

    if not (config := plugin_def.get("config")):
        return

    exos_plugin_config(config)


def exos_plugin_config(config: dict):
    """
    Called during plugin init, this function is used to set up the default
    credentials to access the EXOS devices.

    Parameters
    ----------
    config: dict
        The dict object as defined in the User configuration file.
    """

    try:
        g_exos.config = EXosPluginConfig.parse_obj(config)
    except ValidationError as exc:
        raise RuntimeError(f"Failed to load EXOS plugin configuration: {str(exc)}")

    g_exos.basic_auth = httpx.BasicAuth(
        username=g_exos.config.env.read.username.get_secret_value(),
        password=g_exos.config.env.read.password.get_secret_value(),
    )

    # If the User provides the admin credential environment variobles, then set
    # up the admin authentication that is used for configruation management

    if admin := g_exos.config.env.admin:
        admin_user = admin.username.get_secret_value()
        adin_passwd = admin.password.get_secret_value()
        g_exos.basic_auth_rw = httpx.BasicAuth(admin_user, adin_passwd)
        g_exos.scp_creds = (admin_user, adin_passwd)
