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
# Public Imports
# -----------------------------------------------------------------------------

from netcad.device import Device

# -----------------------------------------------------------------------------
# Private Imports
# -----------------------------------------------------------------------------

from .exos_dut import EXOSDeviceUnderTest

# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = ["plugin_get_dut"]

# -----------------------------------------------------------------------------
#
#                            CODE BEGINS
#
# -----------------------------------------------------------------------------


def plugin_get_dut(device: Device) -> EXOSDeviceUnderTest:
    """
    This function is the required netcam plugin hook that allows the netcam tool
    to obtain the DUT instance for a specific device.  The device instance MUST*
    have the os_name attribute set to "EXOS".

    Parameters
    ----------
    device: Device
        The device instance used to originate the DUT instance.

    Raises
    ------
    RuntimeError
        When the device instance is not os_name=="EXOS"

    Returns
    -------
    The EXOS device-under-test instance used for operational checking.
    """

    if device.os_name != "exos":
        raise RuntimeError(
            f"Missing required DUT class for device {device.name}, os_name: {device.os_name}"
        )

    return EXOSDeviceUnderTest(device=device)
