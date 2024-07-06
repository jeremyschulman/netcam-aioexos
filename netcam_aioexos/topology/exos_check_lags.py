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

# -----------------------------------------------------------------------------
# System Imports
# -----------------------------------------------------------------------------

import asyncio
from collections import defaultdict

# -----------------------------------------------------------------------------
# Public Imports
# -----------------------------------------------------------------------------

from netcad.feats.topology.checks.check_lags import (
    LagCheckCollection,
    LagCheck,
    LagCheckResult,
    LagCheckExpectedInterfaceStatus,
)

from netcad.device import Device, DeviceInterface
from netcad.checks import CheckResultsCollection

# -----------------------------------------------------------------------------
# Private Imports
# -----------------------------------------------------------------------------

from ..exos_dut import EXOSDeviceUnderTest


# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------


@EXOSDeviceUnderTest.execute_checks.register  # noqa
async def exos_check_lags(
    self, testcases: LagCheckCollection
) -> CheckResultsCollection:
    """
    This chcek-executor validates that the LAGs on the device match those as
    defined in the design.
    """

    dut: EXOSDeviceUnderTest = self
    device = dut.device

    # -------------------------------------------------------------------------
    # Get the LACP status from the device
    # -------------------------------------------------------------------------

    cli_lacp_resp = await dut.exos_jrpc.cli("show lacp")

    lacp_ports = [
        lacp_port for rec in cli_lacp_resp if (lacp_port := rec.get("lacpLagCfg"))
    ]
    lacp_group_ids = [lacp["group_id"] for lacp in lacp_ports]

    lacp_group_details = await asyncio.gather(
        *(
            dut.exos_jrpc.cli("show lacp lag {port_id}".format(port_id=port_id))
            for port_id in lacp_group_ids
        )
    )

    lacp_by_group = defaultdict(dict)

    # NOTE: This code **ASSUMES** the designer is using the convention where
    # the name of the lag interface is "lag" + the group_id.  This mechanism is
    # employed because the LACP group_id values are overlapping with actual
    # port ID numbers.

    for lacp_member_info in lacp_group_details:
        lacp_port = lacp_member_info[0]["lacpLagCfg"]["group_id"]
        lacp_port_cfg = [
            port_cfg
            for rec in lacp_member_info
            if (port_cfg := rec.get("lagMemberPortCfg"))
        ]
        if_name = "lag" + lacp_port
        lacp_by_group[if_name]["lacp"] = lacp_member_info
        lacp_by_group[if_name]["interfaces"] = lacp_port_cfg

    # -------------------------------------------------------------------------

    results = list()

    for check in testcases.checks:
        if_name = check.check_id()

        # If the expected LAG does not exist raise that failure and continue
        # with the next interface.

        if not (lag_status := lacp_by_group.get(if_name)):
            result = LagCheckResult(device=device, check=check, measurement=None)
            results.append(result)
            continue

        _check_one_lag(
            device=device, check=check, lag_status=lag_status, results=results
        )

    return results


def _check_one_lag(
    device: Device, check: LagCheck, lag_status: dict, results: CheckResultsCollection
):
    """
    Validates the checks for one specific LAG on the device.
    """

    po_interfaces = lag_status["interfaces"]
    po_if_names = [if_data["port_number"] for if_data in po_interfaces]

    result = LagCheckResult(device=device, check=check)
    msrd = result.measurement

    # -------------------------------------------------------------------------
    # check the interface bundle status.  we will use a defaultdict-list to
    # find any non-bundled values.  If the "CD" flags are set in the interface
    # actor-state, this means that the interface is bundled; that is
    # "collecting-distributing".  The "bundle_status" is a set of True/False of
    # interfaces that are bundled (true) or not (false).
    # -------------------------------------------------------------------------

    bundle_status = defaultdict(list)

    for if_data in po_interfaces:
        if_name = if_data["port_number"]
        bundle_status["CD" in if_data["actor_state"]].append(if_name)

    lag_down = len(bundle_status[False]) == len(po_interfaces)

    # -------------------------------------------------------------------------
    # Check for any missing or extra interfaces in the port-channel liss.
    # -------------------------------------------------------------------------

    msrd.enabled = not lag_down

    msrd.interfaces = [
        LagCheckExpectedInterfaceStatus(
            enabled=bundle_status.get(if_name, True), interface=if_name
        )
        for if_name in sorted(
            po_if_names,
            key=lambda _ifname: DeviceInterface(_ifname, interfaces=device.interfaces),
        )
    ]

    results.append(result.measure())
