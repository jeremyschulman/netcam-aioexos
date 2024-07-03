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

from netcad.checks import CheckResultsCollection
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

__all__ = ()

# -----------------------------------------------------------------------------
#
#                                 CODE BEGINS
#
# -----------------------------------------------------------------------------

ttp_template = """
SysName:          {{hostname}}
System Type:      {{product_model}}
"""


@EXOSDeviceUnderTest.execute_checks.register  # noqa
async def exos_check_device_info(
    self, device_checks: DeviceInformationCheckCollection
) -> CheckResultsCollection:
    """
    The check executor to validate the device information.  Presently this
    function validates the product-model value.  It also captures the results
    of the 'show version' into a check-inforamation.
    """
    dut: EXOSDeviceUnderTest = self

    # extract the hostname and product_model from the text output.  These
    # commands, while having a JSON-RPC equivalent, simply emit the value in
    # text anyway.  boo.

    switch_info_txt = await self.exos.cli("show switch", text=True)
    parser = ttp(switch_info_txt[0], ttp_template)
    parser.parse()
    switch_info = parser.result()[0][0]

    # store the results.
    check = device_checks.checks[0]

    has_product_model = switch_info["product_model"]

    result = DeviceInformationCheckResult(
        device=dut.device,
        check=check,
        measurement=DeviceInformationCheckResult.Measurement(
            product_model=has_product_model
        ),
    )
    return [result]
