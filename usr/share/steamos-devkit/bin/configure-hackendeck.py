#!/usr/bin/env python3
# Streamlining hackendeck setups

import sys
import os
import subprocess
import logging

KSSHASKPASS = '/usr/bin/ksshaskpass'
SSHD_CONFIG = '/etc/ssh/sshd_config'

if __name__ == '__main__':
    logging.basicConfig(format='%(message)s', level=logging.DEBUG)
    logger = logging.getLogger(__name__)

    hackendeck = ( subprocess.run('grep -e "^ID=manjaro$" /etc/os-release', shell=True).returncode == 0 )
    if not hackendeck:
        # plz send patches
        logger.info('Only supported on Manjaro - please check documentation')
        sys.exit(1)

    logger.info('======== Running hackendeck configuration checks ==========')
    assert os.path.exists(KSSHASKPASS)
    os.environ['SUDO_ASKPASS'] = KSSHASKPASS
    # this goes pear shaped because of LD_* scout runtime
    #need_tk = ( subprocess.run('pacman -Q tk', shell=True).returncode != 0 )
    need_tk = not os.path.exists('/usr/lib/libtk.so')
    if need_tk:
        logger.info('Installing Tk library')
        subprocess.check_call('sudo -A pacman --noconfirm -S tk', shell=True)
    logger.info('Tk library is installed')
    enable_sshd = ( subprocess.run('systemctl status sshd 2>&1 >/dev/null', shell=True).returncode != 0 )
    if enable_sshd:
        logger.info('sshd needs to be enabled')
        subprocess.check_call('sudo -A systemctl enable --now sshd', shell=True)
    logger.info('sshd is enabled')
    logger.info('======== hackendeck configuration complete ==========')
