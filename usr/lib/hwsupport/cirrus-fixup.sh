#!/bin/bash

cd $1

# EV1 Cirrus Amp settings, as programmed by EC on cold boot
echo -n "0x00002C04 0x00000420" > registers
echo -n "0x00002C04 0x00000430" > registers
echo -n "0x00002C0C 0x00000003" > registers
echo -n "0x00004804 0x00000021" > registers
echo -n "0x00004808 0x20200200" > registers
echo -n "0x00004800 0x00010003" > registers
echo -n "0x00004820 0x00000101" > registers
echo -n "0x00006800 0x00070405" > registers
echo -n "0x00006C04 0x00000153" > registers
echo -n "0x00002018 0x00003721" > registers
echo -n "0x00003400 0x00003200" > registers
echo -n "0x00003804 0x00000002" > registers
echo -n "0x0000201C 0x01000110" > registers
echo -n "0x0000242C 0x00020000" > registers
echo -n "0x0000242C 0x02020000" > registers
echo -n "0x00010118 0xFFFF87FD" > registers
echo -n "0x00002014 0x00000001" > registers
