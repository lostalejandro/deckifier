#
# Makefile for InsydeFlash tool for Linux (build your main kernel)
#
MACHINE:=$(shell uname -r)
## Default
KERNEL_DIR=/lib/modules/$(MACHINE)/build
CROSS_COMPILE=
## Specific kernel and compiler
# KERNEL_DIR=/home/kanos/Downloads/buildroot-2015.05/output/build/linux-3.12.1
# CROSS_COMPILE=/home/kanos/Downloads/buildroot-2015.05/output/host/usr/bin/x86_64-buildroot-linux-uclibc-
# KERNEL_DIR=/toolkit/source/linux-3.10.x
# CROSS_COMPILE=/usr/local/x86_64-pc-linux-gnu/bin/x86_64-pc-linux-gnu-

obj-m+=phy_alloc.o
LIB_PATH += /usr/lib/insyde/driver/

LBITS := $(shell getconf LONG_BIT)
ifeq ($(LBITS),64)
  EXTRA_CFLAGS += -D__X86_64__
endif

ccflags-y += $(EXTRA)

all: phy_alloc

install:
	mkdir -p $(LIB_PATH)
	cp ./phy_alloc.ko $(LIB_PATH)
		
remove:
	rm -rf $(LIB_PATH)
	
phy_alloc:
	make -C ${KERNEL_DIR} M=$(PWD) CROSS_COMPILE=${CROSS_COMPILE} modules

clean:
	make -C ${KERNEL_DIR} M=$(PWD) clean
	rm -f test

embedded:
	KCFLAGS=-D__STATIC_REGISTER make -C ${KERNEL_DIR} M=$(PWD) CROSS_COMPILE=${CROSS_COMPILE}  modules

