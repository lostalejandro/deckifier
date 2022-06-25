#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import click
import crcmod
import datetime
import errno
import hid
import math
import os
import struct
import sys
import time
import json
import logging
import subprocess

from datetime import datetime
from enum import IntEnum

sys.path.append(os.path.dirname(__file__))

from d21bootloader16 import dog_enumerate, get_dev_build_timestamp

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
ch.setFormatter(formatter)
LOG.addHandler(ch)

#
# Should be updated every time EV2_D20_DBG.bin or EV2_DBG.bin change
#
TEST_APP_BUILD_DAY = datetime(2021, 12, 4)

ID_GET_ATTRIBUTES_VALUES    = 0x83
ID_REBOOT_INTO_ISP          = 0x90
ID_FIRMWARE_UPDATE_REBOOT   = 0x95

ID_FIRMWARE_ERASE_ROW       = 0xB1
ID_FIRMWARE_WRITE_32B       = 0xB2
ID_FIRMWARE_READ_32B        = 0xB3
ID_SET_PARAM                = 0xB4
ID_GET_PARAM                = 0xB5
ID_GET_UNIQUE_ID            = 0xB6

HID_ATTRIB_PRODUCT_ID          = 1
HID_ATTRIB_FIRMWARE_BUILD_TIME = 4
HID_ATTRIB_BOARD_REVISION      = 9

HW_ID_D20_HYBRID = 29
HW_ID_D21_HYBRID = 30
HW_ID_D21_HOMOG  = 31

DEBUG_SET_FORCE_CRC_CHECK   = 0x800F
DEBUG_BOOTLOADER_REASON     = 0x8010

NVMCTRL_AUX0_ADDRESS        = 0x00804000

# ID_ALL_COMMANDS = (ID_GET_ATTRIBUTES_VALUES,
#                    ID_REBOOT_INTO_ISP,
#                    ID_FIRMWARE_UPDATE_START,
#                    ID_FIRMWARE_UPDATE_DATA,
#                    ID_FIRMWARE_UPDATE_COMPLETE,
#                    ID_FIRMWARE_UPDATE_ACK,
#                    ID_FIRMWARE_UPDATE_REBOOT)


MAX_SERIAL_LENGTH           = 30
DEVICE_INFO_MAGIC	    = 0xBEEFFACE
DEVICE_HEADER_VERSION       = 1

FIRMWARE_PAGE_SIZE          = 64
HID_EP_SIZE                 = 64  # TODO: Can this be read from report descriptor?
FLASH_SIZE                  = 256 * 1024
FLASH_END                   = 0x000000000 + FLASH_SIZE
FLASH_ERASE_SIZE            = 256
APP_FW_START                = 0x4000
APP_FW_END                  = FLASH_SIZE - 4 * 1024
APP_FW_INFO                 = APP_FW_END - 4
APP_FW_LENGTH               = APP_FW_INFO - APP_FW_START

INFO_OFFSET                 = FLASH_END - 4096
BLOB_OFFSET                 = INFO_OFFSET + FLASH_ERASE_SIZE

VALVE_USB_VID               = 0x28de
JUPITER_BOOTLOADER_USB_PID  = 0x1004
JUPITER_USB_PID             = 0x1205
JUPITER_CONTROL_INTERFACE   = 2

USB_ENUMERATION_DELAY_S     = 5.0

CRCFUN   = lambda d: crcmod.mkCrcFun(0x104C11DB7)(d, 0)
CRCALIGN = 4
CRCLEN   = struct.calcsize("<I")

def compute_crc(data, size):
    l = len(data)
    data = bytes(data) + bytes(0xFF for _ in range(0, size - len(data)))
    return CRCFUN(data)


class DogBootloaderVerifyError(Exception):
    pass

class DogBootloaderTimeout(Exception):
    pass

class DogBootloaderMCU(IntEnum):
    PRIMARY = 0
    SECONDARY = 1

def bytes_to_stripped_ascii(b):
    try:
        return b.rstrip(b'\xff').rstrip(b'\x00').decode("ascii")
    except UnicodeDecodeError:
        return ""

class DogBootloaderMTEBlob:
    STRUCT = struct.Struct(f"<IB{FLASH_ERASE_SIZE - CRCLEN - 2}s" +
                           "B" # NULL termination
                           )
    assert(STRUCT.size == FLASH_ERASE_SIZE)

    def __init__(self, blob):
        if isinstance(blob, str):
            self.mte_blob = blob
        else:
            crc, _, mte_blob, _ = self.STRUCT.unpack(blob)

            valid = compute_crc(blob[CRCLEN:], FLASH_ERASE_SIZE - 4) == crc
            self.mte_blob = bytes_to_stripped_ascii(mte_blob) if valid else ""

    def __str__(self):
        return self.mte_blob

    def __bytes__(self):
        mte_blob = self.mte_blob.encode("ascii")
        blob     = self.STRUCT.pack(0x00000000,
                                    0x00,
                                    mte_blob,
                                    0x00)
        return self.STRUCT.pack(compute_crc(blob[CRCLEN:], FLASH_ERASE_SIZE - 4),
                                0x00,
                                mte_blob,
                                0x00)

class DogBootloaderDeviceInfo:
    def __init__(self, blob):
        self.struct = struct.Struct(f"<IIII{MAX_SERIAL_LENGTH}s{MAX_SERIAL_LENGTH}s")
        blob = blob[:self.struct.size]

        crc, magic, ver, hw_id, board_serial, unit_serial = self.struct.unpack(blob)

        if magic != DEVICE_INFO_MAGIC     or \
           ver   != DEVICE_HEADER_VERSION or \
           crc   != compute_crc(blob[CRCLEN:], FLASH_ERASE_SIZE - 4):
            board_serial = bytes()
            unit_serial  = bytes()

        board_serial = bytes_to_stripped_ascii(board_serial)
        unit_serial  = bytes_to_stripped_ascii(unit_serial)

        self.hw_id        = hw_id
        self.board_serial = board_serial
        self.unit_serial  = unit_serial

    def __bytes__(self):
        board_serial = self.board_serial.encode("ascii")
        unit_serial  = self.unit_serial.encode("ascii")

        padding = bytes(0xFF for _ in range(0, FLASH_ERASE_SIZE - self.struct.size))
        blob    = self.struct.pack(0x00000000,
                                   DEVICE_INFO_MAGIC,
                                   DEVICE_HEADER_VERSION,
                                   self.hw_id,
                                   board_serial,
                                   unit_serial)

        return self.struct.pack(compute_crc(blob[CRCLEN:], FLASH_ERASE_SIZE - 4),
                                DEVICE_INFO_MAGIC,
                                DEVICE_HEADER_VERSION,
                                self.hw_id,
                                board_serial,
                                unit_serial) + padding

class DogBootloaderAttributes:
    ATTR = struct.Struct("<BL")

    def __init__(self, blob):
        self.build_timestamp = 0
        self.secondary_build_timestamp = 0

        blob = bytes(blob)

        assert len(blob) % self.ATTR.size == 0

        for _ in range(len(blob) // self.ATTR.size):
            t, v = self.ATTR.unpack(blob[:self.ATTR.size])
            blob = blob[self.ATTR.size:]

            attr = {
                HID_ATTRIB_FIRMWARE_BUILD_TIME : "build_timestamp",
                HID_ATTRIB_BOARD_REVISION: "hardware_id",
            }.get(t)

            if attr:
                self.__dict__[attr] = v



class DogBootloader:
    BOOTLOADER_REASON = {
        0x01 : "magic key combo",
        0x02 : "requested by the app",
        0x03 : "left/right handshake",
        0x0B : "bad app start address",
        0x0C : "bad app stack address",
        0x0D : "bad app CRC",
        0x0E : "WDT boot loop",
        0x0F : "MCU mismatch",
    }

    @staticmethod
    def find_app_interface_path():
        ifaces = hid.enumerate(VALVE_USB_VID, JUPITER_USB_PID)

        if ifaces and len(ifaces) >= 3:
            if sys.platform == 'win32':
                ifaces = [i for i in ifaces if i['usage_page'] >= 0xFF00]
            else:
                ifaces = [i for i in ifaces if
                          i['interface_number'] == JUPITER_CONTROL_INTERFACE]

            return ifaces[0]['path']

        return None

    @staticmethod
    def find_mcu_interface_path(mcu):
        def iface_match_p(i):
            if i['interface_number'] == mcu:
                return True
            #
            # Libhidapi won't be able to find interface number on
            # Windows when enumerating devices with a single
            # interface. So to make this work with D21 devices we add
            # the following clause.
            #
            # Note that will still error out when trying to get
            # Secondary's interface on D21 since that's not possible
            # by design (doesn't have one).
            #
            elif sys.platform == 'win32' and mcu == 0:
                return i['interface_number'] == -1
            else:
                return False

        ifaces = hid.enumerate(VALVE_USB_VID, JUPITER_BOOTLOADER_USB_PID)
        ifaces = [i for i in ifaces if iface_match_p(i)]

        return ifaces[0]['path']

    def __init__(self, mcu=DogBootloaderMCU.PRIMARY, reset=True):
        self.mcu = mcu
        #
        # App firmware would have three HID interfaces,
        # so we need to select the right one. Ours is the one with
        # vendor usage page, so select it.
        #
        path = DogBootloader.find_app_interface_path()
        if path:
            if reset:
                LOG.info('Looks like we are running an app. Resetting into bootloader')
                with hid.Device(path=path) as self.hiddev:
                    self.app = self.attributes
                    self._reboot_into_isp()
            else:
                self.hiddev = hid.Device(path=path)
                return

            timeout = USB_ENUMERATION_DELAY_S    # seconds
            delay   = 0.1
            dev     = None
            for i in range(int(timeout / delay)):
                if hid.enumerate(VALVE_USB_VID,
                                 JUPITER_BOOTLOADER_USB_PID):
                    break

                time.sleep(delay)
            else:
                raise DogBootloaderTimeout("Timed out waiting for bootloader to enumerate")

            #
            # HACK: Not sure why a sleep here is necessary, but it
            # seems that hid.enumerate() can retrun a positive
            # result before it can be opened with hidapi.hid_open
            # ¯\_(ツ)_/¯
            #
            time.sleep(USB_ENUMERATION_DELAY_S)

            path = DogBootloader.find_mcu_interface_path(mcu)
            self.hiddev = hid.Device(path=path)

        else:
            path = DogBootloader.find_mcu_interface_path(mcu)
            self.hiddev = hid.Device(path=path)

            if reset:
                self.reset()
                time.sleep(1)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.close()

    def __repr__(self):
        side = "Primary" if self.mcu == DogBootloaderMCU.PRIMARY else "Secondary"
        return f"DogBootloader[{side}]"

    def close(self):
        self.hiddev.close()

    def _reboot_into_isp(self):
        self.send([ID_REBOOT_INTO_ISP,
                   0x04,
                   0x00,
                   0x00,
                   0x00,
                   0x00])

    @property
    def attributes(self):
        self.send([ID_GET_ATTRIBUTES_VALUES])
        payload = self.recv()
        command = payload[0]
        length  = payload[1]
        report  = payload[2:2 + length]

        assert command == ID_GET_ATTRIBUTES_VALUES

        return DogBootloaderAttributes(report)

    def describe(self):
        LOG.info("Found a D20/D21 bootloader device")
        LOG.info("----------------------------")
        info = hid.enumerate(VALVE_USB_VID,
                             JUPITER_BOOTLOADER_USB_PID)[0]

        LOG.info(f"Path: {info['path'].decode()}")
        LOG.info(f"VID: 0x{info['vendor_id']:x}")
        LOG.info(f"PID: 0x{info['product_id']:x}")

        build_time_utc = datetime.utcfromtimestamp(self.bl_firmware_build_time)
        LOG.info(f"Bootloader FW Build Time: 0x{self.bl_firmware_build_time:x} ({build_time_utc} UTC)")

        LOG.info(f"** {self} Unit **")
        LOG.info(f'Stored board serial: {self.board_serial}')
        LOG.info(f'Stored hardware ID: {self.hardware_id}')
        LOG.info("MCU unique ID: {:08X} {:08X} {:08X} {:08X}"
                 .format(*self.unique_id))
        LOG.info("MCU user row: {:02X} {:02X} {:02X} {:02X} {:02X} {:02X} {:02X} {:02X}"
                 .format(*self.user_row))

        LOG.info(f"MCU bootloader mode reason: {self.bootloader_reason}")
        LOG.info("----------------------------")

    @property
    def user_row(self):
        row = self.read_32b(NVMCTRL_AUX0_ADDRESS)
        return row[:8]

    @property
    def unique_id(self):
        STRUCT = struct.Struct("<BBIIII")
        self.send([ID_GET_UNIQUE_ID])

        uid = [0] * 4
        rsp = self.recv()
        _, _, *uid = STRUCT.unpack(rsp[:STRUCT.size])

        return uid

    @property
    def bootloader_reason(self):
        STRUCT = struct.Struct("<BBHL")
        self.send(STRUCT.pack(ID_GET_PARAM,
                              struct.calcsize('<HL'),
                              DEBUG_BOOTLOADER_REASON,
                              0x0000_0000)) # dummy value
        _, _, _, reason = STRUCT.unpack(self.recv()[:STRUCT.size])

        return self.BOOTLOADER_REASON.get(reason, "Bogus value")

    @property
    def bl_firmware_build_time(self):
        return self.attributes.build_timestamp

    @property
    def app_build_datetime(self):
        return self.attributes.build_timestamp

    @property
    def secondary_app_build_datetime(self):
        return self.attributes.secondary_build_timestamp

    def reset(self):
        #
        # If device is already in the bootloader, sending
        # ID_REBOOT_INTO_ISP will reset its state similar to USB
        # reset.
        #
        # Not using libusb to issue a reset because:
        #
        #  1. It doesn't work on Windows. You can use libusb on
        #  Windows, but it requires dissociateing the device from hid
        #  driver, which we can't do
        #
        #  2. USB reset can't be used with libhidapi-libusb variant
        #  since libusb has no mechanism to be notified of external
        #  (to libhidapi-libusb internals) USB resets which break any
        #  outstanding USB deivce structs that were created prior.
        #
        self._reboot_into_isp()

    def send(self, msg):
        msg   = bytes(msg)
        zeros = bytes(0x00 for i in range(len(msg), HID_EP_SIZE))

        self.hiddev.send_feature_report(bytes([0x00]) + msg + zeros)

    def recv(self):
        msg = self.hiddev.get_feature_report(0x00, HID_EP_SIZE + 1)
        return msg[1:]

    def write_32b(self, offset, data):
        LOG.debug(f"writing data @ 0x{offset:08x}")
        fmt = "<BBI"
        self.send(struct.pack(fmt,
                              ID_FIRMWARE_WRITE_32B,
                              struct.calcsize("<I") + 32,
                              offset) + bytes(data))

    def read_32b(self, offset):
        LOG.debug(f"reading data @ 0x{offset:08x}")
        fmt = "<BBI"
        self.send(struct.pack(fmt,
                              ID_FIRMWARE_READ_32B,
                              struct.calcsize("<I"),
                              offset))
        data = self.recv()
        data = data[struct.calcsize(fmt):]
        return data[:32]

    def erase_row(self, offset):
        LOG.debug(f"erasing row @ 0x{offset:08x}")
        fmt = "<BBI"
        self.send(struct.pack(fmt,
                              ID_FIRMWARE_ERASE_ROW,
                              struct.calcsize("<I"),
                              offset))

    def erase(self):
        for offset in range(APP_FW_START, APP_FW_END, FLASH_ERASE_SIZE):
            self.erase_row(offset)

    def read_row(self, offset):
        row = bytes()
        for _ in range(0, FLASH_ERASE_SIZE, 32):
            row    += self.read_32b(offset)
            offset += 32
        #
        # Needs to be bytearray so it would be modifiable
        #
        return bytearray(row)

    def write_row(self, offset, data):
        assert len(data) == FLASH_ERASE_SIZE

        for _ in range(0, FLASH_ERASE_SIZE, 32):
            self.write_32b(offset, data[:32])
            offset += 32
            data    = data[32:]

    def update_row(self, offset, data):
        self.erase_row(offset)
        self.write_row(offset, data)

    def download_firmware(self, size):
        LOG.info(f"Download firmware from {self}, size: {size}")

        data = bytes()
        for offset in range(APP_FW_START, APP_FW_START + size, 32):
            data += self.read_32b(offset)

        return data[:size]

    def update_crc(self, crc):
        crc = bytes(crc)
        assert len(crc) == 4, "We expect 4 byte/32-bit CRC"
        offset = APP_FW_END - FLASH_ERASE_SIZE
        row = self.read_row(offset)
        row[-len(crc):] = crc
        self.update_row(offset, row)

    def do_crc_fixup(self, valid=True):
        blob = self.download_firmware(size=APP_FW_LENGTH)
        crc  = bytearray(struct.pack("<I", compute_crc(blob, APP_FW_LENGTH)))
        if not valid:
            crc[0] = ~crc[0] & 0xFF
        self.update_crc(crc)

    def upload_firmware(self, name, populate_crc=True):
        with open(name, "rb") as f:
            blob = f.read()

        assert len(blob) <= APP_FW_LENGTH, \
            f"Firmware size ({len(blob)}) must be smaller than {APP_FW_LENGTH} bytes"

        #
        # Append enough 0xFFs to our firmware blob to make its size a
        # multiple of FLASH_ERASE_SIZE. We need to erase all unused
        # space anyway, so this'll help us to keep things simple
        #
        if len(blob) % FLASH_ERASE_SIZE:
            blob += bytes(0xFF for _ in range(0, FLASH_ERASE_SIZE -
                                              len(blob) % FLASH_ERASE_SIZE))

        LOG.info(f"Uploading {name} to {self}, size: {len(blob)}")
        LOG.info("Writing whole erase rows first")
        for offset in range(0, len(blob), FLASH_ERASE_SIZE):
            self.update_row(APP_FW_START + offset,
                            blob[offset : offset + FLASH_ERASE_SIZE])
        #
        # Erase the remainder of the Flash, since that's what we
        # assume when generating APP partition CRC
        #
        for offset in range(APP_FW_START + len(blob), APP_FW_END,
                            FLASH_ERASE_SIZE):
            self.erase_row(offset)

        LOG.info("Reading written data back for verification")

        firmware = self.download_firmware(size=len(blob))

        if blob != firmware:
            raise DogBootloaderVerifyError()

        if populate_crc:
            crc = struct.pack("<I", compute_crc(blob, APP_FW_LENGTH))
            self.update_crc(crc)

    @property
    def info(self):
        return DogBootloaderDeviceInfo(self.read_row(INFO_OFFSET))

    @info.setter
    def info(self, value):
        assert type(value) is DogBootloaderDeviceInfo
        self.update_row(INFO_OFFSET, bytes(value))

    @property
    def hardware_id(self):
        return self.attributes.hardware_id

    @hardware_id.setter
    def hardware_id(self, value):
        value = int(value)

        info = self.info
        info.hw_id = value
        self.info = info

    @property
    def unit_serial(self):
        return self.info.unit_serial

    @unit_serial.setter
    def unit_serial(self, value):
        value = str(value)
        assert len(value) < MAX_SERIAL_LENGTH
        assert value, "Unit serial can't be empty"

        info = self.info
        info.unit_serial = value
        self.info = info

    @property
    def board_serial(self):
        return self.info.board_serial

    @board_serial.setter
    def board_serial(self, value):
        value = str(value)
        assert len(value) < MAX_SERIAL_LENGTH
        assert value, "Unit serial can't be empty"

        info = self.info
        info.board_serial = value
        self.info = info

    @property
    def mte_blob(self):
        return DogBootloaderMTEBlob(self.read_row(BLOB_OFFSET))

    @mte_blob.setter
    def mte_blob(self, val):
        self.update_row(BLOB_OFFSET,
                        bytes(DogBootloaderMTEBlob(str(val))))

    def reboot(self, wait_for_app=False):
        self.send([
            ID_FIRMWARE_UPDATE_REBOOT,
        ])

        if wait_for_app:
            timeout = USB_ENUMERATION_DELAY_S    # seconds
            delay   = 0.1
            path     = None
            for i in range(int(timeout / delay)):
                if DogBootloader.find_app_interface_path():
                    break;

                time.sleep(delay)
            else:
                raise DogBootloaderTimeout()
            #
            # HACK: Not sure why a sleep here is necessary, but it
            # seems that hid.enumerate() can retrun a positive
            # result before it can be opened with hidapi.hid_open
            # ¯\_(ツ)_/¯
            #
            time.sleep(USB_ENUMERATION_DELAY_S)


    def set_force_crc_check(self, on=True):
        self.send(struct.pack("<BBHL",
                              ID_SET_PARAM,
                              struct.calcsize('<HL'),
                              DEBUG_SET_FORCE_CRC_CHECK,
                              on))



@click.group()
def cli():
    pass

def dog(primary):
    mcu = DogBootloaderMCU.PRIMARY if primary else DogBootloaderMCU.SECONDARY
    return DogBootloader(mcu=mcu)

@cli.command()
@click.option('--primary/--secondary', default=True)
def getblbuildtimestamp(primary):
    with dog(primary) as bootloader:
        print(bootloader.bl_firmware_build_time)
    print('SUCCESS')

@cli.command()
@click.option('--primary/--secondary', default=True)
def erase(primary):
    with dog(primary) as bootloader:
        bootloader.erase()
    print('SUCCESS')

@cli.command()
@click.option('--primary/--secondary', default=True)
def addcrc(primary):
    with dog(primary) as bootloader:
        bootloader.do_crc_fixup(valid=True)
    print('SUCCESS')

@cli.command()
@click.option('--primary/--secondary', default=True)
def getinfo(primary):
    with dog(primary) as bootloader:
        bootloader.describe()
    print('SUCCESS')

@cli.command()
def getdevicesjson():
  rawdevs = [ *dog_enumerate(JUPITER_USB_PID), *dog_enumerate(JUPITER_BOOTLOADER_USB_PID) ]
  devs = [ { **item,
             'build_timestamp': get_dev_build_timestamp(item)[0],
             'secondary_build_timestamp': get_dev_build_timestamp(item)[1],
             'is_bootloader': item['product_id'] == JUPITER_BOOTLOADER_USB_PID,
             'path': item['path'].decode('utf-8') }
           for item in rawdevs ]

  print(json.dumps(devs))

@cli.command()
@click.option('--primary/--secondary', default=True)
def getappbuildtimestamp(primary):
    vid = VALVE_USB_VID
    pid = JUPITER_USB_PID

    if sys.platform == 'win32':
        devs =  [d for d in hid.enumerate(vid, pid)
            if d['usage_page'] >= 0xFF00]
    else:
        devs = hid.enumerate(vid, pid)

    if len(devs) > 1:
        devs = [d for d in devs if
                d['interface_number'] == JUPITER_CONTROL_INTERFACE]

    # Disallow report when multiple controllers are connected
    if len(devs) > 1:
        print('Multiple controllers detected.')
        print('ERROR')
        return

    if len(devs) == 0:
        print('No Controller found at VID: {} PID: {}'.format(hex(vid), hex(pid)))
        print('ERROR')
        return

    if primary:
        print(get_dev_build_timestamp(devs[0])[0])
    else:
        print(get_dev_build_timestamp(devs[0])[1])

    print('SUCCESS')

@cli.command()
@click.option('--primary/--secondary', default=True)
@click.option('--clean', is_flag=True, help="Clean output")
def gethwid(primary, clean):
    with dog(primary) as bootloader:
        if clean:
            print(bootloader.hardware_id)
        else:
            print(f'HW ID: {bootloader.hardware_id}')
            print('SUCCESS')

@cli.command()
@click.option('--primary/--secondary', default=True)
@click.argument('hardware_id', type=int)
def sethwid(primary, hardware_id):
    with dog(primary) as bootloader:
        bootloader.hardware_id = hardware_id
    print('SUCCESS')

@cli.command()
@click.option('--primary/--secondary', default=True)
def getserial(primary):
    with dog(primary) as bootloader:
        print(f"Serial: {bootloader.board_serial}")

    print('SUCCESS')

@cli.command()
@click.option('--primary/--secondary', default=True)
@click.argument('serial', type=str)
def setserial(primary, serial):
    if len(serial) >= MAX_SERIAL_LENGTH:
        serial = serial[:MAX_SERIAL_LENGTH - 1]
        LOG.warn(f"Clamping serial to {serial} to fit maximum length")

    with dog(primary) as bootloader:
        bootloader.board_serial = serial
    print('SUCCESS')

@cli.command()
def getunitserial():
    with dog(True) as bootloader:
        print (f'Unit Serial: {bootloader.unit_serial}')
    print('SUCCESS')

@cli.command()
@click.argument('serial', type=str)
def setunitserial(serial):
    if len(serial) >= MAX_SERIAL_LENGTH:
        serial = serial[:MAX_SERIAL_LENGTH - 1]
        LOG.warn(f"Clamping serial to {serial} to fit maximum length")

    with dog(True) as bootloader:
        bootloader.unit_serial = serial
    print('SUCCESS')

@cli.command()
@click.argument('firmware', type=click.Path(exists=True,
                                            dir_okay=False))
@click.option('--primary/--secondary', default=True)
def program(firmware, primary):
    with dog(primary) as bootloader:
        bootloader.upload_firmware(firmware)
        if primary:
            bootloader.reboot(wait_for_app=True)
    print('SUCCESS')

@cli.command()
@click.option('--primary/--secondary', default=True)
def getblob(primary):
    with dog(primary) as bootloader:
        print('BLOB DATA: "{}"'.format(bootloader.mte_blob))
        print('SUCCESS')

@cli.command()
@click.option('--primary/--secondary', default=True)
@click.argument('blob_str', type=str)
def setblob(primary, blob_str):
    with dog(primary) as bootloader:
        bootloader.mte_blob = blob_str
        print('SUCCESS')

@cli.command()
@click.option('--primary/--secondary', default=True)
def reset(primary):
    with dog(primary) as bootloader:
        bootloader.reboot(wait_for_app=primary) # wait for app to
                                                # enumerate if we are
                                                # rebooting primary
                                                # MCU
    print('SUCCESS')

if __name__ == '__main__':
    try:
        with DogBootloader(mcu=DogBootloaderMCU.PRIMARY,
                           reset=False) as d:
            hardware_id = d.hardware_id

        if not hardware_id in {
                #
                # Assume that if HW ID is not set the user knows what they
                # are doing and can run correct script against their
                # flavor of the bootloader
                #
                0xFFFF_FFFF,
                HW_ID_D21_HYBRID,
                #
                # We should never see HW_ID_D20_HYBRID on PRIMARY,
                # but may as well just check for it
                #
                HW_ID_D20_HYBRID,
                HW_ID_D21_HOMOG
        }:
            import d21bootloader16
            # print(f'Redirecting to d21bootloader16.py due to HW ID of {hardware_id}')
            python = "python" if sys.platform == 'win32' else "python3"
            ret = subprocess.call([python, d21bootloader16.__file__] + sys.argv[1:])
            sys.exit(ret)

        cli()
    except hid.HIDException as e:
        print(e)
        print('ERROR')
    except DogBootloaderTimeout:
        print('TIMEOUT')
    except DogBootloaderVerifyError:
        print('Programmed data mismatch')
        print('ERROR')
