#!/bin/sh

set -e

mkdir -p "$HOME/.xpra"

cd "$(dirname "$0")"
basename="$0"
while basename="$(readlink "$(basename "$basename")")"
do
	cd "$(dirname "$basename")"
done
pwd

test -x trunk/src/install/bin/xpra || (
	modules="libx11-dev libxtst-dev libxcomposite-dev libxdamage-dev python-gobject-dev python-gtk2-dev xvfb cython libx264-dev libswscale-dev libavcodec-dev libvpx-dev"
	if ! dpkg -l $modules
	then
		sudo apt-get install $modules || exit
	fi
	cd trunk/src
	./setup.py install --home=install
)

export PYTHONPATH=$PWD/trunk/src/install/lib/python:$PYTHONPATH

if test $# = 0
then
	display=98
	case "$HOSTNAME" in
	gene099-iMac)
		set --xvfb="Xorg -verbose -noreset +extension GLX +extension RANDR +extension RENDER -logfile $HOME/.xpra/$display.log -config $PWD/xorg.conf :$display" "--start-child=dbus-launch gnome-terminal" start :$display
		;;
	*)
		set attach ssh:bigmac:$display
		;;
	esac
fi
exec ./trunk/src/install/bin/xpra "$@"
