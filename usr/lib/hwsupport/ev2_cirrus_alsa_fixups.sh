#!/bin/bash

# These tend to persist, but they're not right on first boot
# TODO call is_ev2.sh (doesn't exist yet) to only run it there?
# TODO how to run once at startup? should be short-lived so maybe we can just run everytime

amixer -c 1 set "Left AMP Enable" unmute
amixer -c 1 set "Right AMP Enable" unmute

amixer -c 1 set "Left AMP PCM Gain" 70%
amixer -c 1 set "Right AMP PCM Gain" 70%

amixer -c 1 set "Left Digital PCM" 817
amixer -c 1 set "Right Digital PCM" 817
