#!/bin/bash

TARGET_DIR=.
EXE_FILE=h2offt

if [ -d "driver" -a ! -f "driver/phy_alloc.ko" ]; then
    cd driver
    make clean
    make
    cd -
fi

if [ "$(ls /usr/bin/id 2>/dev/null)" = "/usr/bin/id" ] && [ "$(id -u)" != "0" ]; then
  echo "It should be run as root" 1>&2
  exit 1
fi

./${TARGET_DIR}/${EXE_FILE} $@
exit $?
