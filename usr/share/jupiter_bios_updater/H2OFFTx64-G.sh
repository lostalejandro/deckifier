#!/bin/bash

TARGET_DIR=.
EXE_FILE=h2offt-g
GSUDO_CMD=

if [ -d "driver" -a ! -f "driver/phy_alloc.ko" ]; then
    cd driver
    make clean
    make
    cd -
fi

if [ "$(ls /usr/bin/id 2>/dev/null)" = "/usr/bin/id" ] && [ "$(id -u)" != "0" ]; then
  if [ "$(ls /usr/bin/gksu 2>/dev/null)" = "/usr/bin/gksu" ] ; then
    GSUDO_CMD=/usr/bin/gksu
  elif [ "$(ls /usr/bin/gksudo 2>/dev/null)" = "/usr/bin/gksudo" ] ; then
    GSUDO_CMD=/usr/bin/gksudo
  elif [ "$(ls /usr/bin/kdesudo 2>/dev/null)" = "/usr/bin/kdesudo" ] ; then
    GSUDO_CMD=/usr/bin/kdesudo 
  elif [ "${GSUDO_CMD}" = "" ] ; then
    # echo "It should be run as root" 1>&2
    # exit 1
    GSUDO_CMD=sudo
  fi
fi

${GSUDO_CMD} ./${TARGET_DIR}/${EXE_FILE} $@
exit $?
