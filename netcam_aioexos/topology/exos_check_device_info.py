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
# Public Impors
# -----------------------------------------------------------------------------

from ttp import ttp
from netcad.checks import CheckResultsCollection, CheckResult, CheckStatus
from netcad.feats.topology.checks.check_device_info import (
    DeviceInformationCheckCollection,
    DeviceInformationCheckResult,
)

# -----------------------------------------------------------------------------
# Private Improts
# -----------------------------------------------------------------------------

from netcam_aioexos.exos_dut import EXOSDeviceUnderTest

# -----------------------------------------------------------------------------
# Exports (None)
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
#
#                                 CODE BEGINS
#
# -----------------------------------------------------------------------------


show_version_template = """
<group name="sw_ver_switch">
Switch          : {{ ignore(".*") }} IMG: {{ sw_ver }}
</group>
<group name="sw_ver_stack">
Slot-{{ slot_id }} : {{ ignore(".*") }} IMG: {{ sw_ver }}
</group>
"""
# SysName:          {{ hostname }}

show_switch_template = """
SysName:          {{ hostname }}
System Type:      {{ product_model | _line_ }}
"""


@EXOSDeviceUnderTest.execute_checks.register  # noqa
async def exos_check_device_info(
    self, device_checks: DeviceInformationCheckCollection
) -> CheckResultsCollection:
    """
    This function is used to collect device information from the Extreme EXOS.
    The primary check is the product-model.  Additional information is
    collected and returned as an informational check. This includes the
    hostname, serial number, part number, and software version.
    """
    dut: EXOSDeviceUnderTest = self

    # -------------------------------------------------------------------------
    # get the software version
    # -------------------------------------------------------------------------

    cli_sh_ver = await dut.exos_jrpc.cli("show version", text=True)
    sh_ver_ttp = ttp(data=cli_sh_ver[0], template=show_version_template)
    sh_ver_ttp.parse()
    sh_ver_data = sh_ver_ttp.result()[0][0]
    sh_ver_data = sh_ver_data.get("sw_ver_stack") or sh_ver_data.get("sw_ver_switch")

    # -------------------------------------------------------------------------
    # get the switch information
    # -------------------------------------------------------------------------

    cli_sh_switch = await dut.exos_jrpc.cli("show switch", text=True)
    sh_sw_ttp = ttp(data=cli_sh_switch[0], template=show_switch_template)
    sh_sw_ttp.parse()
    sh_sw_data = sh_sw_ttp.result()[0][0]
    product_model = sh_sw_data["product_model"]
    hostname = sh_sw_data["hostname"]

    # store the results.
    check = device_checks.checks[0]
    has_product_model = product_model

    return [
        # product model check
        DeviceInformationCheckResult(
            device=dut.device,
            check=check,
            measurement=DeviceInformationCheckResult.Measurement(
                product_model=has_product_model
            ),
        ),
        # add an informational block with the device details.
        CheckResult(
            device=dut.device,
            check=check,
            status=CheckStatus.INFO,
            measurement=dict(
                hostname=hostname,
                software_version=sh_ver_data,
            ),
        ),
    ]
