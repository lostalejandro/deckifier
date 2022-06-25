/*
 * Physical memory allocate Driver
 * File: phy_alloc.c
 *
 * Copyright (C) 2013 - 2015 Insyde Software Corp.
 *
 * This software is licensed under the terms of the GNU General Public
 * License version 2, as published by the Free Software Foundation, and
 * may be copied, distributed, and modified under those terms.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 */
#include "phy_alloc.h"

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/ioctl.h>
#include <linux/slab.h>
#include <linux/version.h>
#include <asm/page.h>
#include <linux/cdev.h>
#include <linux/types.h>
#include <linux/errno.h>
#include <linux/sched.h>
#include <linux/fcntl.h>
#include <linux/device.h>
#include <linux/poll.h>
#include <asm/uaccess.h>
#include <asm/io.h>
#include <linux/string.h>
#include <linux/uaccess.h>
#include <linux/vmalloc.h>
#include <linux/delay.h>

#include <linux/mm.h>

#define Drv_VERSION         "0x00000008"
#define DRIVER_AUTHOR       "Insyde"
#define DRIVER_DESC         "Insyde physical memory allocate driver"

// #define __DEBUG_MODE__
#ifdef __DEBUG_MODE__
  #define KDBG(m,...)      printk (KERN_DEBUG m, ##__VA_ARGS__)
#else
  #define KDBG(m,...)
#endif

#ifdef __STATIC_REGISTER
  #define NUMBER_MAJOR      231 //0xf2
  #define NUMBER_MINOR      0
#endif

static unsigned int gAllocatedQuantity = 0;
static int gDeviceOpen = 0;
#ifndef __STATIC_REGISTER
  static int DrvMajor = 0, DrvMinor = 0;
  static dev_t DrvDev;
  static struct class *pDrvDevClass = NULL;
#endif

unsigned int t_dwEAX;
unsigned int t_dwEBX;
unsigned int t_dwECX;
unsigned int t_dwEDX;
unsigned int t_dwEDI;
unsigned int t_dwESI;

#ifndef LINUX_VERSION_CODE
  // Some linux distro, for example, Linpus with kernel 4.2.8 has duplicate version.h 
  // and it may have no LINUX_VERSION_CODE defined in another version.h
  // Include specific version.h while LINUX_VERSION_CODE isn't defined
  #include "/usr/include/linux/version.h"
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION( 2, 6, 36 )
  static DEFINE_MUTEX( drv_mutex );
#endif

#pragma pack(1)

struct DrvDev_st {
  struct cdev cdev;
} st_DrvDev;

//
// Internal record list for allocate physcial detail information.
//
typedef struct _st_obj ST_OBJ;
struct _st_obj {
  ST_OBJ *pNext; // Next record, if "null" that's end of records.
  ST_OBJ *pLast; // Last record, if "null" that's first of records.
  unsigned int Index; // Allocate memory index for check and search with user mode information.
  unsigned long Size; // Allocated physical memory size
  unsigned long long KernelVirtualAddress; // Allocated physical memory virtual address in kernel space
  unsigned long long KernelLogicalAddress; // Allocated physical memory physical address in kernel space 
  unsigned char *pBuffer; // Virtual address for user space allocated memory
};
ST_OBJ *gpObjList = NULL;

#pragma pack()


//
// Allocate physical memory
//
static int Alloc_Physical_Memory (unsigned long arg)
{
  ST_OBJ *pstObj = NULL;
  ST_OBJ *pLastObj = NULL;
  ST_PHY_ALLOC stPhyAlloc = {0};
  ST_PHY_ALLOC *pstPhyAlloc = &stPhyAlloc;
  unsigned char *pBuffer = NULL;
  unsigned int Index = 0;
    int    iOrder = -1;

  if (copy_from_user (pstPhyAlloc, (void *) arg, sizeof (ST_PHY_ALLOC))) {
    return DRV_FAILED;
  }

  KDBG ("pstPhyAlloc->Size=0x%x\n", pstPhyAlloc->Size);

  // Allocate size must beigger then 0.
  if(!pstPhyAlloc->Size) 
    return ARGUMENT_FAIL;

  // Allocate physical memory.
  while ( (1 << ++iOrder)* PAGE_SIZE < pstPhyAlloc->Size);
#ifdef __x86_64__
  pBuffer = (void *)__get_free_pages( GFP_DMA32 | GFP_ATOMIC, iOrder);
#else
  pBuffer = (void *)__get_free_pages( GFP_ATOMIC, iOrder);
#endif
  if(!pBuffer) {
    // Allocate physical memory return fail.
    KDBG ("Alloc buffer failed\n");
    return ALLOCATE_FAIL;
  }
  memset (pBuffer, 0, pstPhyAlloc->Size);

  // Add a new record into internal record list
  if(gpObjList==NULL) { // First record
    KDBG ("Allocate root list\n");
    gpObjList = vmalloc(sizeof(ST_OBJ));
    if (!gpObjList) {
      kfree (pBuffer);
      KDBG ("Allocate root list failed\n");
      return ALLOCATE_FAIL;
    }
    memset(gpObjList, 0, sizeof(ST_OBJ));
    pstObj=gpObjList;
  } else { // Add a new record follow record list
    pstObj=gpObjList;
    while(pstObj->pNext) {
      pstObj=pstObj->pNext;
      if (pstObj->Index>=Index) {
        Index=pstObj->Index;
      }
    }
    Index++;
    KDBG ("Allocate next node\n");
    pstObj->pNext=(ST_OBJ*)vmalloc(sizeof(ST_OBJ));
    if (!pstObj->pNext) {
      kfree (pBuffer);
      KDBG ("Allocate node failed\n");
      return ALLOCATE_FAIL;
    }
    memset(pstObj->pNext, 0, sizeof(ST_OBJ));
    pLastObj = pstObj;
    pstObj=pstObj->pNext;
  }

  KDBG ("Update node...\n");
    // Update record informations
  pstObj->pLast = pLastObj;
  pstObj->pBuffer = pBuffer;
  pstObj->KernelLogicalAddress = virt_to_phys(pstObj->pBuffer);
  pstObj->KernelVirtualAddress = (unsigned long)pstObj->pBuffer;
  pstObj->Index = Index;
  pstObj->Size = pstPhyAlloc->Size;

  // Update information for user space application
  pstPhyAlloc->VirtualAddress  = pstObj->KernelVirtualAddress;
  pstPhyAlloc->PhysicalAddress = pstObj->KernelLogicalAddress;
  pstPhyAlloc->Index = pstObj->Index;

  if (copy_to_user ((void *) arg, pstPhyAlloc, sizeof (ST_PHY_ALLOC))) {
    return DRV_FAILED;
  }

  gAllocatedQuantity++;
  return DRV_SUCCESS;
}


//
// Release allocated physical memory
//
static int Free_Physical_Memory (unsigned long arg)
{
  ST_OBJ *pstObj = NULL;
  ST_OBJ *pLastObj = NULL;
  ST_OBJ *pNextObj = NULL;
  ST_PHY_ALLOC stPhyAlloc = {0};
  ST_PHY_ALLOC *pstPhyAlloc = &stPhyAlloc;
  int    iOrder = -1;

  if (copy_from_user (pstPhyAlloc, (void *) arg, sizeof (ST_PHY_ALLOC))) {
    return DRV_FAILED;
  }

  if(gpObjList) {
    pstObj=gpObjList;
    while(true) {
      if(pstObj->KernelLogicalAddress==pstPhyAlloc->PhysicalAddress) {
        if ((pstObj->pNext==NULL) && (pstObj->pLast==NULL)) { /* Only one record */
          gpObjList = NULL;
        } else if ((pstObj->pNext!=NULL) && (pstObj->pLast!=NULL)) { /* Record  betweet head and last */
          pLastObj = pstObj->pLast;
          pNextObj = pstObj->pNext;
          pLastObj->pNext = pNextObj;
          pNextObj->pLast = pLastObj;
        } else if (pstObj->pNext==NULL) { /* Last record */
          pLastObj = pstObj->pLast;
          pLastObj->pNext = NULL;
        } else if (pstObj->pLast==NULL) { /* First record */
          gpObjList = pstObj->pNext;
        }

        while ( (1 << ++iOrder)* PAGE_SIZE < pstPhyAlloc->Size);
        free_pages ((unsigned long)pstObj->pBuffer, iOrder);
        vfree(pstObj);
        gAllocatedQuantity--;
        return DRV_SUCCESS;
      } else if (pstObj->pNext) {
        pstObj = pstObj->pNext;
      } else {
        return ALLOCATE_FAIL;
      }
    }   
  }

  return ALLOCATE_FAIL;
}


//
// Read physical memory to virtual memory in user space
//
static int Read_Physical_Memory (unsigned long arg)
{
  ST_OBJ *pstObj = NULL;
  ST_PHY_ALLOC stPhyAlloc = {0};
  ST_PHY_ALLOC *pstPhyAlloc = &stPhyAlloc;

  if (copy_from_user (pstPhyAlloc, (void *) arg, sizeof (ST_PHY_ALLOC))) {
    return DRV_FAILED;
  }

  if (pstPhyAlloc->pBuffer==NULL) {
    return ALLOCATE_FAIL;
  }

  if(gpObjList) {
    pstObj=gpObjList;
    while(true) {
      if (pstPhyAlloc->Index==pstObj->Index) {
        if (copy_to_user (pstPhyAlloc->pBuffer, pstObj->pBuffer, pstObj->Size)) {
          return DRV_FAILED;
        }
        return DRV_SUCCESS;
      } else if (pstObj->pNext) {
        pstObj = pstObj->pNext;
      } else {
        return ALLOCATE_FAIL;
      }
    }   
  }

  return ALLOCATE_FAIL;
}


//
// Write physical memory from virtual memory in user space
//
static int Write_Physical_Memory (const unsigned long arg)
{
  ST_OBJ *pstObj = NULL;
  ST_PHY_ALLOC stPhyAlloc = {0};
  ST_PHY_ALLOC *pstPhyAlloc = &stPhyAlloc;

  if (copy_from_user (pstPhyAlloc, (void *) arg, sizeof (ST_PHY_ALLOC))) {
    return DRV_FAILED;
  }

  if (pstPhyAlloc->pBuffer==NULL) {
    return ALLOCATE_FAIL;
  }

  if(gpObjList) {
    pstObj=gpObjList;
    while(true) {
      if (pstPhyAlloc->Index==pstObj->Index) {
        if (copy_from_user (pstObj->pBuffer, pstPhyAlloc->pBuffer, pstObj->Size)) {
          return DRV_FAILED;
        }
        return DRV_SUCCESS;
      } else if (pstObj->pNext) {
        pstObj = pstObj->pNext;
      } else {
        return ALLOCATE_FAIL;
      }
    }   
  }

  return ALLOCATE_FAIL;
}


static int Version (unsigned int* ptr)
{
  unsigned int version = VERSION_NUMBER_HEX;

  if (!ptr) {
    KDBG ("Version parameter wrong\n");
    return ARGUMENT_FAIL;
  }

  if (copy_to_user (ptr, &version, sizeof (unsigned int))) {
    return DRV_FAILED;
  }

  return DRV_SUCCESS;
}


static int AllocatedQuantity (unsigned int* ptr)
{
  if (copy_to_user (ptr, &gAllocatedQuantity, sizeof (unsigned int))) {
    return DRV_FAILED;
  }

  return DRV_SUCCESS;
}

static int DoIn(DRV_IO *io)
{
  switch (io->size) {
    case 1:
      io->data = inb(io->port) & 0xFF;
      break;
    case 2:
      io->data = inw(io->port) & 0xFFFF;
      break;
    case 4:
      io->data = inl(io->port) & 0xFFFFFFFFUL;
      break;
    case 8: {
      uint32_t *p = (uint32_t*)&io->data;
      p[0] = inl(io->port + 0);
      p[1] = inl(io->port + 4);
      break;
    }
  }
  return DRV_SUCCESS;
}

static int DoOut(DRV_IO *io)
{
  switch (io->size) {
    case 1:
      outb((uint8_t)(io->data & 0xFF), io->port);
      break;
    case 2:
      outw((uint16_t)(io->data & 0xFFFF), io->port);
      break;
    case 4:
      outl((uint32_t)(io->data & 0xFFFFFFFFUL), io->port);
      break;
    case 8: {
      uint32_t *p = (uint32_t*)&io->data;
      outl(p[0], io->port);
      outl(p[1], io->port + 4);
      break;
    }
  }
  return DRV_SUCCESS;
}

static int DoIO (unsigned int* ptr)
{
  DRV_IO io = {0};
  int status = DRV_SUCCESS;
  if (copy_from_user (&io, ptr, sizeof (DRV_IO))) {
    return DRV_FAILED;
  }

  KDBG ("Do IO port = %X data = %llX, size = %d, mode = %d\n", io.port, io.data, io.size, io.mode);
  switch (io.mode) {
    case IO_MODE_READ:
      status = DoIn(&io);
      break;
    case IO_MODE_WRITE:
      status = DoOut(&io);
      break;
  }
  KDBG ("Do IO port = %X data = %llX, size = %d, mode = %d\n", io.port, io.data, io.size, io.mode);
  
  if (copy_to_user (ptr, &io, sizeof (DRV_IO))) {
    return DRV_FAILED;
  }

  return status;
}


static int Drv_Open(struct inode *inode, struct file *file)
{
  int ret = 0;
  gDeviceOpen++;
#if LINUX_VERSION_CODE >= KERNEL_VERSION( 2, 6, 36 )
  mutex_lock( &drv_mutex );
#endif
  ret = try_module_get(THIS_MODULE);
#if LINUX_VERSION_CODE >= KERNEL_VERSION( 2, 6, 36 )
  mutex_unlock( &drv_mutex );
#endif

  if (ret == 0) {
    return DRV_BE_USED;
  }
  return DRV_SUCCESS;
}


static int Drv_Release(struct inode *inode, struct file *file)
{
  gDeviceOpen--;
#if LINUX_VERSION_CODE >= KERNEL_VERSION( 2, 6, 36 )
  mutex_lock( &drv_mutex );
#endif
  module_put(THIS_MODULE);
#if LINUX_VERSION_CODE >= KERNEL_VERSION( 2, 6, 36 )
  mutex_unlock( &drv_mutex );
#endif

  return DRV_SUCCESS;
}

static int SMI (unsigned char* arg)
{
	SMI_REGISTER SmiReg = {0};
	SMI_REGISTER* reg = &SmiReg;

	if (copy_from_user (reg, arg, sizeof (SMI_REGISTER))) {
		return 1;
	}

	KDBG ("EAX: 0x%x\n", reg->dwEAX);
	KDBG ("EBX: 0x%x\n", reg->dwEBX);
	KDBG ("ECX: 0x%x\n", reg->dwECX);
	KDBG ("EDX: 0x%x\n", reg->dwEDX);
	KDBG ("ESI: 0x%x\n", reg->dwESI);
	KDBG ("EDI: 0x%x\n", reg->dwEDI);

	t_dwEAX = reg->dwEAX;
	t_dwEBX = reg->dwEBX;
	t_dwECX = reg->dwECX;
	t_dwEDX = reg->dwEDX;
	t_dwESI = reg->dwESI;
	t_dwEDI = reg->dwEDI;

	__asm__
	(
#ifdef __x86_64__ // for gcc
		"push   %rax    \n"
		"push   %rbx    \n"
		"push   %rcx    \n"
		"push   %rdx    \n"
		"push   %rdi    \n"
		"push   %rsi    \n"
		"xor    %rax,       %rax     \n"
		"xor    %rbx,       %rbx     \n"
#else
		"push   %eax    \n"
		"push   %ebx    \n"
		"push   %ecx    \n"
		"push   %edx    \n"
		"push   %edi    \n"
		"push   %esi    \n"
		"xor    %eax,       %eax     \n"
		"xor    %ebx,       %ebx     \n"
#endif

		"mov    t_dwEAX,    %eax    \n"
		"mov    t_dwEBX,    %ebx    \n"
		"mov    t_dwECX,    %ecx    \n"
		"mov    t_dwEDX,    %edx    \n"
		"mov    t_dwESI,    %esi    \n"
		"mov    t_dwEDI,    %edi    \n"
		"out    %al,        %dx     \n"

		"mov    %eax,       t_dwEAX  \n"
		"mov    %ebx,       t_dwEBX  \n"
		"mov    %ecx,       t_dwECX  \n"
		"mov    %edx,       t_dwEDX  \n"
		"mov    %esi,       t_dwESI  \n"
		"mov    %edi,       t_dwEDI  \n"

#ifdef __x86_64__ // for gcc
		"pop    %rsi    \n"
		"pop    %rdi    \n"
		"pop    %rdx    \n"
		"pop    %rcx    \n"
		"pop    %rbx    \n"
		"pop    %rax    \n"
#else
		"pop    %esi    \n"
		"pop    %edi    \n"
		"pop    %edx    \n"
		"pop    %ecx    \n"
		"pop    %ebx    \n"
		"pop    %eax    \n"
#endif
	);

#if LINUX_VERSION_CODE < KERNEL_VERSION( 3, 0, 0 )
	msleep(500);
#else
	usleep_range (100, 1000);
#endif

	reg->dwEAX = t_dwEAX;
	reg->dwEBX = t_dwEBX;
	reg->dwECX = t_dwECX;
	reg->dwEDX = t_dwEDX;
	reg->dwESI = t_dwESI;
	reg->dwEDI = t_dwEDI;

	if (copy_to_user (arg, reg, sizeof (SMI_REGISTER))) {
		KDBG (KERN_WARNING "Copy Data back to user failed\n");
		return 1;
	}

	KDBG ("Result: 0x%x\n", t_dwEAX);

	return 0;
}

#if LINUX_VERSION_CODE >= KERNEL_VERSION( 2, 6, 36 )
static long Drv_Ioctl(struct file *file, unsigned int num, unsigned long arg)
#else
static int Drv_Ioctl(struct inode *inode, struct file *file, unsigned int num, unsigned long arg)
#endif
{
  long Ret=0;

  KDBG ("num=0x%x\n", num);
  switch (num) {
  case IOCTL_ALLOCATE_MEMORY:
    Ret = Alloc_Physical_Memory (arg);
    break;

  case IOCTL_FREE_MEMORY:
    Ret = Free_Physical_Memory (arg);
    break;

  case IOCTL_WRITE_MEMORY:
    Ret = Write_Physical_Memory (arg);
    break;

  case IOCTL_READ_MEMORY:
    Ret = Read_Physical_Memory (arg);
    break;

  case IOCTL_READ_VERSION:
    Ret = Version ((unsigned int*)arg);
    break;

  case IOCTL_GET_ALLOCATED_QUENTITY:
    Ret = AllocatedQuantity ((unsigned int*)arg);
    break;

  case IOCTL_IO:
    Ret = DoIO ((unsigned int*)arg);
    break;

  case IOCTL_SMI:
      Ret = SMI ( (unsigned char*) arg);
      break;

  default:
    KDBG ("Unsupported!\n");
    Ret = -1;
    break;
  }
  return Ret;
}


#if LINUX_VERSION_CODE >= KERNEL_VERSION( 2, 6, 36 )
static long Drv_Ioctl_Unlock(struct file *fp, unsigned int cmd, unsigned long arg)
{
    long            ret;
    mutex_lock( &drv_mutex );
    ret = Drv_Ioctl( fp, cmd, arg );
    mutex_unlock( &drv_mutex );
    return ret;
}
#endif

/*
 * Architectures vary in how they handle caching for addresses
 * outside of main memory.
 *
 */
#ifdef pgprot_noncached
static int uncached_access(struct file *file, phys_addr_t addr)
{
#if defined(CONFIG_IA64)
	/*
	 * On ia64, we ignore O_DSYNC because we cannot tolerate memory
	 * attribute aliases.
	 */
	return !(efi_mem_attributes(addr) & EFI_MEMORY_WB);
#elif defined(CONFIG_MIPS)
	{
		extern int __uncached_access(struct file *file,
					     unsigned long addr);

		return __uncached_access(file, addr);
	}
#else
	/*
	 * Accessing memory above the top the kernel knows about or through a
	 * file pointer
	 * that was marked O_DSYNC will be done non-cached.
	 */
	if (file->f_flags & O_DSYNC)
		return 1;
	return addr >= __pa(high_memory);
#endif
}
#endif

pgprot_t phys_mem_access_prot(struct file *file, unsigned long pfn,
                              unsigned long size, pgprot_t vma_prot)
{
#ifdef pgprot_noncached
	phys_addr_t offset = pfn << PAGE_SHIFT;

	if (uncached_access(file, offset))
		return pgprot_noncached(vma_prot);
#endif
	return vma_prot;
}

#ifndef CONFIG_MMU
/* can't do an in-place private mapping if there's no MMU */
static inline int private_mapping_ok(struct vm_area_struct *vma)
{
	return vma->vm_flags & VM_MAYSHARE;
}
#else
static inline int private_mapping_ok(struct vm_area_struct *vma)
{
	return 1;
}
#endif

static const struct vm_operations_struct mmap_mem_ops = {
#ifdef CONFIG_HAVE_IOREMAP_PROT
	.access = generic_access_phys
#endif
};

static int Drv_Map ( struct file *file, struct vm_area_struct *vma )
{
	size_t size = vma->vm_end - vma->vm_start;
	phys_addr_t offset = (phys_addr_t)vma->vm_pgoff << PAGE_SHIFT;

	/* Does it even fit in phys_addr_t? */
	if (offset >> PAGE_SHIFT != vma->vm_pgoff)
		return -EINVAL;

	/* It's illegal to wrap around the end of the physical address space. */
	if (offset + (phys_addr_t)size - 1 < offset)
		return -EINVAL;

	if (!private_mapping_ok(vma))
		return -ENOSYS;

	vma->vm_page_prot = phys_mem_access_prot(file, vma->vm_pgoff,
						 size,
						 vma->vm_page_prot);

	vma->vm_ops = &mmap_mem_ops;

	/* Remap-pfn-range will mark the range VM_IO */
	if (remap_pfn_range(vma,
			    vma->vm_start,
			    vma->vm_pgoff,
			    size,
			    vma->vm_page_prot)) {
		return -EAGAIN;
	}
	return 0;
}

static struct file_operations fops = {
    .owner = THIS_MODULE,
    .open = Drv_Open,
    #if LINUX_VERSION_CODE >= KERNEL_VERSION( 2, 6, 36 )
      .unlocked_ioctl = Drv_Ioctl_Unlock,
      .compat_ioctl = Drv_Ioctl_Unlock, // To allow 32-bits userland programs to make ioctl calls on a 64-bits kernel.
    #else
      .ioctl = Drv_Ioctl,
    #endif
    .release = Drv_Release,
    .mmap   = Drv_Map,
};

#ifdef __STATIC_REGISTER
//Driver initialization
static int __init Init_Drv(void)
{
  if (register_chrdev (NUMBER_MAJOR, DEVICE_NAME, &fops) < 0)
    return DRV_INITIAL_FAIL;

  KDBG ("IOCTL_ALLOCATE_MEMORY=0x%x\n", IOCTL_ALLOCATE_MEMORY);
  KDBG ("IOCTL_FREE_MEMORY=0x%x\n", IOCTL_FREE_MEMORY);
  KDBG ("IOCTL_WRITE_MEMORY=0x%x\n", IOCTL_WRITE_MEMORY);
  KDBG ("IOCTL_READ_MEMORY=0x%x\n", IOCTL_READ_MEMORY);
  KDBG ("IOCTL_READ_VERSION=0x%x\n", IOCTL_READ_VERSION);
  KDBG ("IOCTL_GET_ALLOCATED_QUENTITY=0x%x\n", IOCTL_GET_ALLOCATED_QUENTITY);

  return 0;
}
static void __exit Cleanup_Drv(void)
{
    unregister_chrdev (NUMBER_MAJOR, DEVICE_NAME);
}
#else

static void cleanup(int created)
{
    if (created) {
#if LINUX_VERSION_CODE < KERNEL_VERSION(2,6,26)
        class_device_destroy (pDrvDevClass, DrvDev);
#else
        device_destroy (pDrvDevClass, DrvDev);
#endif
        cdev_del(&st_DrvDev.cdev);
    }
    if (pDrvDevClass)
        class_destroy(pDrvDevClass);
    if (MKDEV (DrvMajor, 0) != -1)
        unregister_chrdev_region(MKDEV (DrvMajor, 0), 1);
}

//Driver initialization
static int __init Init_Drv(void)
{
  dev_t devno;
  struct device *class_dev = NULL;
  int created = 0;

  if (DrvMajor) {
    devno = MKDEV (DrvMajor, 0);
    if (register_chrdev_region (devno, 1, DEVICE_NAME) < 0)
      goto error;
  } else {
    if (alloc_chrdev_region (&devno, 0, 1, DEVICE_NAME) < 0)
      goto error;
  }

  DrvMajor = MAJOR (devno);
  DrvMinor = MINOR (devno);

  // Create device node
  pDrvDevClass = class_create (THIS_MODULE, DEVICE_NAME);
  if (IS_ERR (pDrvDevClass))
    goto error;

  DrvDev = MKDEV (DrvMajor, DrvMinor);

#if LINUX_VERSION_CODE < KERNEL_VERSION(2,6,26)
  class_dev = class_device_create ((struct class *)pDrvDevClass, (struct class_device *)NULL, DrvDev, (struct device *)NULL, DEVICE_NAME);
#else
  class_dev = device_create (pDrvDevClass, NULL, DrvDev, NULL, DEVICE_NAME);
#endif

  created = 1;
  // Initial cdev
  cdev_init (&st_DrvDev.cdev, &fops);
  st_DrvDev.cdev.owner = THIS_MODULE;
  st_DrvDev.cdev.ops = &fops;

  // Regist device
  if (cdev_add (&st_DrvDev.cdev, devno, 1))
    goto error; 

  KDBG ("IOCTL_ALLOCATE_MEMORY=0x%x\n", IOCTL_ALLOCATE_MEMORY);
  KDBG ("IOCTL_FREE_MEMORY=0x%x\n", IOCTL_FREE_MEMORY);
  KDBG ("IOCTL_WRITE_MEMORY=0x%x\n", IOCTL_WRITE_MEMORY);
  KDBG ("IOCTL_READ_MEMORY=0x%x\n", IOCTL_READ_MEMORY);
  KDBG ("IOCTL_READ_VERSION=0x%x\n", IOCTL_READ_VERSION);
  KDBG ("IOCTL_GET_ALLOCATED_QUENTITY=0x%x\n", IOCTL_GET_ALLOCATED_QUENTITY);

  return DRV_SUCCESS;
error:
  cleanup(created);
  return DRV_INITIAL_FAIL;
}

static void __exit Cleanup_Drv(void)
{
  ST_OBJ *pObj = NULL;
  ST_OBJ *pNext = NULL;
  int    iOrder = -1;

  if (gDeviceOpen) {
    return;
  } else {
    if (gpObjList) {
      pObj = gpObjList;
      while(true) {
        pNext = pObj->pNext;
        while ( (1 << ++iOrder)* PAGE_SIZE < pObj->Size);
        free_pages ((unsigned long)pObj->pBuffer, iOrder);
        vfree(pObj);
        if (pNext==NULL) {
          break;
        } else {
          pObj = pNext;
        }
      }
      gpObjList = NULL;
    }
  }

  cleanup(1);
}
#endif


module_init( Init_Drv);
module_exit( Cleanup_Drv);

MODULE_AUTHOR( DRIVER_AUTHOR );
MODULE_DESCRIPTION( DRIVER_DESC );
MODULE_VERSION( Drv_VERSION );
MODULE_SUPPORTED_DEVICE( "Insyde" );
MODULE_LICENSE( "GPL" );
