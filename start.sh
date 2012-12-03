#!/bin/sh

set -e

mkdir -p "$HOME/.xpra"

cd "$(dirname "$0")"

test -x src/install/bin/xpra || (
	modules="libx11-dev libxtst-dev libxcomposite-dev libxdamage-dev python-gobject-dev python-gtk2-dev xvfb cython libx264-dev libswscale-dev libavcodec-dev libvpx-dev"
	if ! dpkg -l $modules
	then
		sudo apt-get install $modules || exit
	fi
	cd src
	./setup.py install --home=install
)

DISPLAY=98
export PYTHONPATH=$PWD/src/install/lib/python:$PYTHONPATH
./src/install/bin/xpra --xvfb="Xorg -verbose -noreset +extension GLX +extension RANDR +extension RENDER -logfile $HOME/.xpra/$DISPLAY.log -config $PWD/xorg.conf :$DISPLAY" "--start-child=dbus-launch gnome-terminal" start :$DISPLAY
