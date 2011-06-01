#!/bin/bash

if [ -z "${DISTS}" ]; then
	DISTS="hardy intrepid jaunty karmic lenny squeeze sid lucid"
fi

for dist in ${DISTS}; do
	rm -f dists/${dist}/Release*
	apt-ftparchive release dists/${dist} > dists/${dist}-Release
	echo "Origin: xpra.devloop.org.uk" >> dists/${dist}/Release
	if [ "${dist}" == "lenny" ] || [ "${dist}" == "squeeze" ]; then
		echo "Label: Debian" >> dists/${dist}/Release
	else
		echo "Label: Ubuntu" >> dists/${dist}/Release
	fi
	echo "Suite: ${dist}" >> dists/${dist}/Release
	echo "Codename: ${dist}" >> dists/${dist}/Release
#Date: Wed, 22 Apr 2009 21:35:16 UTC
#Version: 9.04
	echo "Architectures: amd64 i386" >> dists/${dist}/Release
	echo "Components: main" >> dists/${dist}/Release
# Description: Ubuntu Jaunty 9.04
	cat dists/${dist}-Release >> dists/${dist}/Release
	rm dists/${dist}-Release
	gpg -abs -o dists/${dist}/Release.gpg dists/${dist}/Release
done
