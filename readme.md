# Deck-ifier

***SteamOS session on any Arch-based distro!***

This repository aims to add required SteamDeck's holo packages and binaries such as `steamos-update, jupiter-biosupdate, steamosatomupd`, the Gamescope Wayland session and other required components to Arch Linux

This adds all of the required SteamOS dependencies, as well as everything needed for shader pre-cache downloading, FPS;TDP;GPU clock limiting, flyouts, update daemon, performance overlay and so on

## Known Bugs/issues: 

- Battery status doesn't work on some devices
- global FSR doesn't work (normal due to mesa/linux doesn't support that by default)
- Probably more which isn't documented here

<div style="font-size: 12px;color: grey;">
Global FSR Note:

You can install SteamOS3 Mesa and linux-neptune, from aur if you need it. Just run `yay -S linux-steamos linux-steamos-headers mesa-steamos`, then reboot using new kernel
</div>

<!-- old readme bugs list -->
<!-- currently i don't know how to enable battery status for laptops, global FSR doesn't work (intended behavior, since extra/mesa and core/linux kernel doesn't support that. You may install SteamOS3 mesa and linux-neptune later if you want to try it) -->

## Pre-requisites
Before installing, make sure the `multilib` repository is enabled in /etc/pacman.conf and that you [have `yay` installed](https://github.com/Jguer/yay#installation).

**the installation will fail otherwise!**

## Installation:

Open a Terminal and do the following:
```
git clone https://github.com/lostalejandro/deckifier.git
cd deckifier
chmod +x deckifier.sh
./deckifier.sh --install
```
you can also do --help instead to see a small summary of available options


## Credits:

To theVakhovske, the creator of this script that eventually evolved to holoISO.
To Gamescope, Valve and Steam developers.
To anyone involved on this amazing software.