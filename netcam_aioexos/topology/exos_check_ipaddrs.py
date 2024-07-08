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

from typing import Sequence

# -----------------------------------------------------------------------------
# Public Imports
# -----------------------------------------------------------------------------

from netcad.feats.topology.checks.check_ipaddrs import (
    IPInterfacesCheckCollection,
    IPInterfaceCheck,
    IPInterfaceCheckResult,
    IPInterfaceExclusiveListCheck,
    IPInterfaceExclusiveListCheckResult,
)

from netcad.device import Device, DeviceInterface
from netcad.checks import CheckResultsCollection, CheckStatus, CheckResult

# -----------------------------------------------------------------------------
# Private Imports
# -----------------------------------------------------------------------------

from netcam_aioexos.exos_dut import EXOSDeviceUnderTest


# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = []


# -----------------------------------------------------------------------------
#
#                                 CODE BEGINS
#
# -----------------------------------------------------------------------------


@EXOSDeviceUnderTest.execute_checks.register  # noqa
async def exos_test_ipaddrs(
    dut, collection: IPInterfacesCheckCollection
) -> CheckResultsCollection:
    """
    This check executor validates the IP addresses used on the device against
    those that are defined in the design.
    """

    dut: EXOSDeviceUnderTest

    device = dut.device

    # run the command to get the IP address assignments.  Need to filter the
    # specific record entries "ifIpConfig" as other data is mixed into this CLI
    # response.

    cli_ipcfg_rsp = await dut.exos_jrpc.cli("show ipconfig")
    cli_mgmt_rsp = await dut.exos_jrpc.cli("show Mgmt")
    msrd_mgmt_data = cli_mgmt_rsp[0]["vlanProc"]

    dev_ipcfgs = [
        cfg for rec in cli_ipcfg_rsp
        if (cfg := rec.get("ifIpConfig")) and cfg['ipAddress'] != '0.0.0.0'
    ]

    dev_vlan_ifcfgs = {
        vlan_name: cfg for cfg in dev_ipcfgs
        if (vlan_name := cfg.get("vlan"))
    }

    results = list()
    if_names = list()

    for check in collection.checks:
        if_name = check.check_id()
        if_names.append(if_name)

        # if the OOB management port is expected in the design, then check this
        # value specifically since there is a bespoke command to get this
        # information.

        if if_name.casefold() == "mgmt":
            results.append(
                await _check_mgmt_interface(
                    msrd_data=msrd_mgmt_data, device=device, check=check
                )
            )
            continue

        # if the IP address does not exist, then report that measurement and
        # move on to the next interface.

        if not (if_ip_data := dev_vlan_ifcfgs.get(if_name)):
            results.append(
                IPInterfaceCheckResult(
                    device=device, check=check, measurement=None
                ).measure()
            )
            continue

        await _check_one_interface(
            dut,
            device=device,
            check=check,
            msrd_data=if_ip_data,
            results=results,
            # TODO: hardcoding this to True for now; until we find a case where
            #       the IP is assigned to a physical interface (like mgmt)
            is_vlan=True,
        )

    # only include device interface that have an assigned IP address; this
    # conditional is checked by examining the interface IP address mask length
    # against zero.

    msrd_if_name = list(dev_vlan_ifcfgs)
    if msrd_mgmt_data.get("ipAddress") != '0.0.0.0':
        msrd_if_name.append("Mgmt")

    if collection.exclusive:
        _check_exclusive_list(
            device=device,
            expd_if_names=if_names,
            msrd_if_names=msrd_if_name,
            results=results,
        )

    return results


# -----------------------------------------------------------------------------


async def _check_mgmt_interface(
    msrd_data: dict,
    device: Device,
    check: IPInterfaceCheck,
) -> CheckResult:
    """
    This function checks the IP assignment on the dedicated managmenet
    interface ("Mgmt").  There is a bespoke command on EXOS for this purpose.
    """

    result = IPInterfaceCheckResult(device=device, check=check)
    msrd = result.measurement
    msrd.if_ipaddr = f"{msrd_data['ipAddress']}/{msrd_data['maskForDisplay']}"
    msrd.oper_up = msrd_data["linkState"] == 1
    return result.measure()


# -----------------------------------------------------------------------------


async def _check_one_interface(
    dut: "EXOSDeviceUnderTest",
    device: Device,
    check: IPInterfaceCheck,
    msrd_data: dict,
    results: CheckResultsCollection,
    is_vlan: bool,
):
    """
    This function validates a specific interface use of an IP address against
    the design expectations.
    """

    if_name = check.check_id()
    result = IPInterfaceCheckResult(device=device, check=check)
    msrd = result.measurement

    # -------------------------------------------------------------------------
    # if there is any error accessing extracting interface IP address
    # information, then yeild a failure and return.
    # -------------------------------------------------------------------------

    try:
        msrd.if_ipaddr = f"{msrd_data['ipAddress']}/{msrd_data['prefixLen']}"

    except KeyError:
        result.measurement = None
        results.append(result.measure())
        return results

    # -------------------------------------------------------------------------
    # Ensure the IP interface value matches.
    # -------------------------------------------------------------------------

    expd_if_ipaddr = check.expected_results.if_ipaddr

    # if the IP address is marked as "is_reserved" it means that an external
    # entity configured the IP address, and this check will only record the
    # value as an INFO check result.

    if expd_if_ipaddr == "is_reserved":
        result.status = CheckStatus.INFO
        results.append(result.measure())

    # -------------------------------------------------------------------------
    # Ensure the IP interface is "up".
    # TODO: should check if the interface is enabled before presuming this
    #       up condition check.
    # -------------------------------------------------------------------------

    # check to see if the interface is disabled before we check to see if the IP
    # address is in the up condition.

    dut_interfaces = dut.device_info["interfaces"]
    dut_iface = dut_interfaces[if_name]
    iface_enabled = dut_iface["enabled"] is True

    # if "U" is set in the flags, then it means the interface is Up.
    msrd.oper_up = "U" in msrd_data["flags"]

    if iface_enabled and not msrd.oper_up:
        # if the interface is an SVI, then we need to check to see if _all_ of
        # the associated physical interfaces are either disabled or in a
        # reseverd condition.

        if is_vlan:
            await _check_vlan_assoc_interface(
                dut, if_name=if_name, result=result, results=results
            )
            return results

    results.append(result.measure())
    return results


def _check_exclusive_list(
    device: Device,
    expd_if_names: Sequence[str],
    msrd_if_names: Sequence[str],
    results: CheckResultsCollection,
):
    """
    This check determines if there are any extra IP Interfaces defined on the
    device that are not expected per the design.
    """

    # the previous per-interface checks for any missing; therefore we only need
    # to check for any extra interfaces found on the device.

    def sort_key(i):
        return DeviceInterface(i, interfaces=device.interfaces)

    result = IPInterfaceExclusiveListCheckResult(
        device=device,
        check=IPInterfaceExclusiveListCheck(expected_results=expd_if_names),
        measurement=sorted(msrd_if_names, key=sort_key),
    )
    results.append(result.measure())


async def _check_vlan_assoc_interface(
    dut: EXOSDeviceUnderTest,
    if_name: str,
    result: IPInterfaceCheckResult,
    results: CheckResultsCollection,
):
    """
    This function is used to check whether a VLAN SVI ip address is not "up"
    due to the fact that the underlying interfaces are either disabled or in a
    "reserved" design; meaning we do not care if they are up or down. If the
    SVI is down because of this condition, the test case will "pass", and an
    information record is yielded to inform the User.

    Parameters
    ----------
    dut:
        The device under test

    result:
        The result instance bound to the check

    if_name:
        The specific VLAN SVI name, "Vlan12" for example:

    Yields
    ------
    netcad test case results; one or more depending on the condition of SVI
    interfaces.
    """

    cli_res = await dut.exos_jrpc.cli(f"show vlan {if_name}")

    # store the port and the link-state (bool)
    vlan_if_ports = dict()
    for rec in cli_res:
        if not (vlan_proc := rec.get("vlanProc")):
            continue
        port = vlan_proc["port"]
        if_up = vlan_proc["linkState"] == 1  # 0=down, 1=up
        vlan_if_ports[port] = if_up

    dut_ifs = dut.device_info["interfaces"]

    # set of disregarded interfaces based on design.
    disrd_ifnames = set()

    for check_ifname in vlan_if_ports:
        dut_iface = dut_ifs[check_ifname]
        if (dut_iface["enabled"] is False) or (
            "is_reserved" in dut_iface["profile_flags"]
        ):
            disrd_ifnames.add(check_ifname)

    if disrd_ifnames == set(vlan_if_ports):
        # then the SVI check should be a PASS because of the conditions
        # mentioned.

        result.logs.log(
            CheckStatus.INFO,
            "oper_up",
            dict(
                message="interfaces are either disabled or in reserved state",
                interfaces=list(vlan_if_ports),
            ),
        )

        def on_mismatch(_field, _expd, _msrd):
            return CheckStatus.PASS if _field == "oper_up" else CheckStatus.FAIL

        results.append(result.measure(on_mismatch=on_mismatch))

    return results
