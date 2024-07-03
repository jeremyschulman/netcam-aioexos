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

# =============================================================================
# This file contains the EXOS "Device Under Test" class definition.  This is
# where the specific check-executors are wired into the class to support the
# various design-service checks.
# =============================================================================

# -----------------------------------------------------------------------------
# System Imports
# -----------------------------------------------------------------------------

import asyncio
from typing import Optional
from functools import singledispatchmethod

# -----------------------------------------------------------------------------
# Public Imports
# -----------------------------------------------------------------------------

import httpx
from aioexos.jsonrpc import Device as DeviceEXOS

from netcad.device import Device
from netcad.checks import CheckCollection, CheckResultsCollection
from netcam.dut import AsyncDeviceUnderTest, SetupError

# -----------------------------------------------------------------------------
# Privae Imports
# -----------------------------------------------------------------------------

from .exos_plugin_globals import g_exos
from .aio_portcheck import port_check_url


# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = ["EXOSDeviceUnderTest"]


# -----------------------------------------------------------------------------
#
#                                 CODE BEGINS
#
# -----------------------------------------------------------------------------


class EXOSDeviceUnderTest(AsyncDeviceUnderTest):
    """
    This class provides the Arista EXOS device-under-test plugin for directly
    communicating with the device via the JSONRPC interface.  The underpinning
    transport is using asyncio.  Refer to the `aioexos` distribution for
    further details.
    """

    def __init__(self, *, device: Device, **_kwargs):
        """DUT construction creates instance of EXOS API transport"""

        super().__init__(device=device)

        self.exos = DeviceEXOS(
            host=device.name, auth=g_exos.basic_auth, timeout=g_exos.config.timeout
        )
        self.system_info: Optional[dict] = None

        # inialize the DUT cache mechanism; used exclusvely by the
        # `api_cache_get` method.

        self._api_cache_lock = asyncio.Lock()
        self._api_cache = dict()

    # -------------------------------------------------------------------------
    #
    #                       EXOS DUT Specific Methods
    #
    # -------------------------------------------------------------------------

    async def api_cache_get(self, key: str, command: str, **kwargs) -> dict | str:
        """
        This function is used by other class methods that want to abstract the
        collection function of a given API routine so that the results of that
        call are cached and avaialble for other check executors.  This method
        should not be called outside other methods of this DUT class, but this
        is not a hard constraint.

        For example, if the result of "show interface switchport" is going to be
        used by multiple check executors, then there would exist a method in
        this class called `get_switchports` that uses this `api_cache_get`
        method.

        Parameters
        ----------
        key: str
            The cache-key string that is used to uniquely identify the contents
            of the cache.  For example 'switchports' may be the cache key to cache
            the results of the 'show interfaces switchport' command.

        command: str
            The actual EXOS CLI command used to obtain the API results.

        Other Parameters
        ----------------
        Any keyword-args supported by the underlying API Device driver; for
        example `ofmt` can be used to change the output format from the default
        of dict to text.  Refer to the aio-exos package for further details.

        Returns
        -------
        Either the cached data corresponding to the key if exists in the cache,
        or the newly retrieved data from the device; which is then cached for
        future use.
        """
        async with self._api_cache_lock:
            if not (has_data := self._api_cache.get(key)):
                has_data = await self.exos.cli(command, **kwargs)
                self._api_cache[key] = has_data

            return has_data

    # -------------------------------------------------------------------------
    #
    #                              DUT Methods
    #
    # -------------------------------------------------------------------------

    async def setup(self):
        """DUT setup process"""
        await super().setup()

        if not await port_check_url(self.exos.base_url):
            raise SetupError(
                f"Unable to connect to EXOS device: {self.device.name}: "
                "Device offline or EXOS API is not enabled, check config."
            )

        try:
            rsp = await self.exos.cli("show switch", text=True)
            self.system_info = rsp[0]
            # TODO: need to parse this into a structured object.
        except httpx.HTTPError as exc:
            rt_exc = RuntimeError(
                f"Unable to connect to EXOS device {self.device.name}: {str(exc)}"
            )
            rt_exc.__traceback__ = exc.__traceback__
            await self.teardown()
            raise rt_exc

    async def teardown(self):
        """DUT tearndown process"""
        await self.exos.aclose()

    @singledispatchmethod
    async def execute_checks(
        self, checks: CheckCollection
    ) -> Optional[CheckResultsCollection]:
        """
        This method is only called when the DUT does not support a specific
        design-service check.  This function *MUST* exist so that the supported
        checks can be "wired into" this class using the dispatch register mechanism.
        """
        return super().execute_checks()
