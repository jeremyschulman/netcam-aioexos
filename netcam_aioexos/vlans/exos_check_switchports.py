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

from typing import cast
from collections import defaultdict
# -----------------------------------------------------------------------------
# Public Imports
# -----------------------------------------------------------------------------

from netcad.checks import CheckResultsCollection
from netcad.feats.vlans.checks.check_switchports import (
    SwitchportCheckCollection,
    SwitchportCheck,
    SwitchportCheckResult,
)

# -----------------------------------------------------------------------------
# Private Imports
# -----------------------------------------------------------------------------

from ..exos_dut import EXOSDeviceUnderTest

# -----------------------------------------------------------------------------
#
#                                 CODE BEGINS
#
# -----------------------------------------------------------------------------


@EXOSDeviceUnderTest.execute_checks.register  # noqa
async def exos_check_switchports(
    dut, switchport_checks: SwitchportCheckCollection
) -> CheckResultsCollection:
    """
    This check executor validates the device operational status of the interface
    switchports.

    Parameters
    ----------
    dut:
        The DUT instance for the specific device being checked.

    switchport_checks: SwitchportCheckCollection
        The collection of checks created by the netcad tool for the
        vlans.switchports case.

    Returns
    -------
    A collection of check-results that will be logged and reported to the User
    during check execution and showing results.
    """

    dut: EXOSDeviceUnderTest
    device = dut.device
    results = list()

    # ---------------------------------------------------------------------
    # Collect the switchport data from the device.  Build the information into
    # "msrd_switchports" which is a dictionary for each interface. we will
    # collect the untagged and tagged vlans for each port.  Any port that has
    # only untagged will be considered an access port.
    # ---------------------------------------------------------------------

    msrd_switchports = defaultdict(lambda: {"untagged": None, "tagged": list()})

    cli_rsp = await dut.exos_jrpc.cli("show ports vlan port-number")

    for rec in cli_rsp:
        if not (port_info := rec.get("show_ports_info_detail_vlans")):
            continue

        port_id = port_info["port"]
        vlan_id = port_info["vlanId"]
        if port_info["tagStatus"] == 1:
            msrd_switchports[port_id]["tagged"].append(vlan_id)
        else:
            msrd_switchports[port_id]["untagged"] = vlan_id

    # -------------------------------------------------------------------------
    # This next bit has to deal with the way EXOS handles ports in a LAG.  It
    # turns out at least from discovery, that a port in a LAG will reference
    # another port as the source of VLAN config; rather than duplicating it.
    # Therefore, we need to look for this condition so that we explicilty check
    # for the ports in the LAG.
    # -------------------------------------------------------------------------

    for rec in cli_rsp:
        if not (port_info := rec.get("show_ports_info")):
            continue

        if not (ld_share := port_info.get("ldShareMaster")):
            continue

        if (port_id := port_info["port"]) != ld_share:
            if port_id in msrd_switchports:
                continue

            # copy the referenced port switchport data to this port.
            msrd_switchports[port_id] = msrd_switchports[ld_share]

    # -------------------------------------------------------------------------
    # each check represents one interface to validate.  Loop through each of
    # the checks to ensure that the expected switchport use is as expected.
    # -------------------------------------------------------------------------

    for check in switchport_checks.checks:
        if_name = check.check_id()

        # LAG interfaces are not modeled the same as other interfaces.  So we
        # do not check them here in switchports.

        if if_name.startswith("lag"):
            continue

        result = SwitchportCheckResult(device=device, check=check)

        expd_status = cast(SwitchportCheck.ExpectSwitchport, check.expected_results)

        # if the interface from the design does not exist on the device, then
        # report this error and go to next check.

        if not (msrd_port := msrd_switchports.get(if_name)):
            result.measurement = None
            results.append(result.measure())
            continue

        # ensure the expected port mode matches before calling the specific
        # mode check.  if there is a mismatch, then fail now.

        msrd_mode = "trunk" if bool(msrd_port["tagged"]) else "access"
        if expd_status.switchport_mode != msrd_mode:
            result.measurement.switchport_mode = msrd_mode
            results.append(result.measure())
            continue

        # verify the expected switchport mode (access / trunk)
        (
            _check_access_switchport
            if expd_status.switchport_mode == "access"
            else _check_trunk_switchport
        )(result=result, msrd_status=msrd_port, results=results)

    # return the collection of results for all switchport interfaces
    return results


def _check_access_switchport(
    result: SwitchportCheckResult, msrd_status: dict, results: CheckResultsCollection
):
    """
    This function validates that the access port is reporting as expected.
    This primary check here is ensuring the access VLAN-ID matches.
    """

    msrd = result.measurement = SwitchportCheckResult.MeasuredAccess()
    msrd.switchport_mode = "access"

    # the check stores the VlanProfile, and we need to mutate this value to the
    # VLAN ID for comparitor reason.
    result.check.expected_results.vlan = result.check.expected_results.vlan.vlan_id

    # EXOS stores the vlan id as int, so type comparison AOK
    msrd.vlan = msrd_status["untagged"]

    results.append(result.measure())


def _check_trunk_switchport(
    result: SwitchportCheckResult, msrd_status: dict, results: CheckResultsCollection
):
    """
    This function validates a trunk switchport against the expected values.
    These checks include matching on the native-vlan and trunk-allowed-vlans.
    """

    expd = cast(SwitchportCheck.ExpectTrunk, result.check.expected_results)
    msrd = result.measurement = SwitchportCheckResult.MeasuredTrunk()
    msrd.switchport_mode = "trunk"
    msrd.native_vlan = msrd_status["untagged"]

    if expd.native_vlan:
        expd.native_vlan = expd.native_vlan.vlan_id

    expd.trunk_allowed_vlans = sorted(
        set([v.vlan_id for v in expd.trunk_allowed_vlans])
    )
    msrd.trunk_allowed_vlans = sorted(set(msrd_status["tagged"]))

    results.append(result.measure())
