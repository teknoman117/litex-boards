#!/usr/bin/env python3

#
# This file is part of LiteX-Boards.
#
# Copyright (c) 2021 Andrew Dennison <andrew@motec.com.au>
# Copyright (c) 2021 Franck Jullien <franck.jullien@collshade.fr>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2022 Charles-Henri Mousset <ch.mousset@gmail.com>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from litex.gen import *
from litex.gen.genlib.misc import WaitTimer

from litex_boards.platforms import efinix_t8f81_dev_kit

from litex.soc.cores.clock import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.soc import SoCRegion
from litex.soc.integration.builder import *
from litex.soc.cores.led import LedChaser

# CRG ----------------------------------------------------------------------------------------------

class _CRG(LiteXModule):
    def __init__(self, platform, sys_clk_freq):
        self.rst    = Signal()
        self.cd_sys = ClockDomain()
        self.cd_rst = ClockDomain(reset_less=True)

        # # #

        clk33 = platform.request("clk33")
        rst_n = platform.request("user_btn", 0)

        self.comb += self.cd_rst.clk.eq(clk33)

        # A pulse is necessary to do a reset.
        self.rst_pulse = Signal()
        self.reset_timer = reset_timer = ClockDomainsRenamer("rst")(WaitTimer(25e-6*platform.default_clk_freq))
        self.comb += self.rst_pulse.eq(self.rst ^ reset_timer.done)
        self.comb += reset_timer.wait.eq(self.rst)

        # PLL.
        self.pll = pll = TRIONPLL(platform)
        self.comb += pll.reset.eq(~rst_n | self.rst_pulse)
        pll.register_clkin(clk33, platform.default_clk_freq)
        pll.create_clkout(self.cd_sys, sys_clk_freq, with_reset=True)

# BaseSoC ------------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, bios_flash_offset, sys_clk_freq=33.333e6, with_led_chaser=True, **kwargs):
        platform = efinix_t8f81_dev_kit.Platform()

        # CRG --------------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ----------------------------------------------------------------------------------
        # Disable Integrated ROM.
        kwargs["integrated_rom_size"]  = 0
        # Set CPU variant / reset address
        if kwargs.get("cpu_type", "vexriscv") == "vexriscv":
            kwargs["cpu_variant"] = "minimal"
        SoCCore.__init__(self, platform, sys_clk_freq, ident="LiteX SoC on Efinix T8F81 Dev Kit", **kwargs)

        # SPI Flash --------------------------------------------------------------------------------
        from litespi.modules import W25Q80BV
        from litespi.opcodes import SpiNorFlashOpCodes as Codes
        self.add_spi_flash(mode="1x", module=W25Q80BV(Codes.READ_1_1_1), with_master=False)

        # Add ROM linker region --------------------------------------------------------------------
        self.bus.add_region("rom", SoCRegion(
            origin = self.bus.regions["spiflash"].origin + bios_flash_offset,
            size   = 32 * KILOBYTE,
            linker = True)
        )
        self.cpu.set_reset_address(self.bus.regions["rom"].origin)

        # Leds -------------------------------------------------------------------------------------
        if with_led_chaser:
            self.leds = LedChaser(
                pads         = platform.request_all("user_led"),
                sys_clk_freq = sys_clk_freq)

# Build --------------------------------------------------------------------------------------------


def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=efinix_t8f81_dev_kit.Platform, description="LiteX SoC on Efinix T8F81C Dev Kit.")
    parser.add_target_argument("--flash",             action="store_true",          help="Flash Bitstream.")
    parser.add_target_argument("--sys-clk-freq",      default=33.333e6, type=float, help="System clock frequency.")
    parser.add_target_argument("--bios-flash-offset", default="0x40000",            help="BIOS offset in SPI Flash.")

    args = parser.parse_args()

    soc = BaseSoC(
        bios_flash_offset = int(args.bios_flash_offset, 0),
        sys_clk_freq      = args.sys_clk_freq,
        **parser.soc_argdict)
    builder = Builder(soc, **parser.builder_argdict)
    if args.build:
        builder.build(**parser.toolchain_argdict)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.add_hex(0, builder.get_bitstream_filename(mode="sram"))
        prog.load()

    if args.flash:
        prog = soc.platform.create_programmer()
        prog.add_hex(0, builder.get_bitstream_filename(mode="sram"))
        prog.add_bin(int(args.bios_flash_offset, 0), builder.get_bios_filename())
        prog.flash()

if __name__ == "__main__":
    main()
